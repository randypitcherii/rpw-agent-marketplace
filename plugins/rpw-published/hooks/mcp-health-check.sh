#!/bin/bash
# mcp-health-check.sh — UserPromptSubmit hook for the rpw-published plugin.
#
# Detects MCP server failures for THIS marketplace's plugins from the CURRENT
# session's logs and surfaces them so Claude can recommend a repair. Runs once
# per session (gated by a /tmp marker keyed on session_id) so it has no cost on
# subsequent prompts.
#
# OFF by default: on a fresh public install every MCP server fails for lack of
# an env file, which would spam this notice on the user's very first prompt. A
# project/user must opt in — see scripts/orient-gate.sh. When opted in, the
# remediation is credential-source-aware: generic servers point at the README /
# mcp-setup; UC-proxy-specific failures (Databricks) get the UC wording.
#
# Why UserPromptSubmit (not SessionStart): MCP servers boot concurrently with
# (or shortly after) SessionStart, so SessionStart can't read current-session
# log data. UserPromptSubmit fires after MCP startup has had time to write its
# success/failure to log files.
#
# Output: plain text on stdout becomes additional context for the agent.
# Silent when MCPs are healthy, already-checked, or not opted in. Never blocks.

set +e

# --- Opt-in gate (silent by default) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../scripts/orient-gate.sh
source "$SCRIPT_DIR/../scripts/orient-gate.sh" 2>/dev/null || exit 0
rpw_orient_enabled || exit 0

# --- Read stdin JSON (UserPromptSubmit payload) ---
input=$(cat 2>/dev/null)

# Try to extract session_id from JSON; fall back to env var.
session_id=$(printf '%s' "$input" | sed -n 's/.*"session_id":"\([^"]*\)".*/\1/p' | head -1)
[ -z "$session_id" ] && session_id="${CLAUDE_SESSION_ID:-$$}"

# --- Once-per-session gate ---
marker="${TMPDIR:-/tmp}/rpw-mcp-health-${session_id}"
[ -f "$marker" ] && exit 0
mkdir -p "$(dirname "$marker")" 2>/dev/null
touch "$marker" 2>/dev/null

# --- Resolve current-session log dir (per-platform) ---
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Claude Code's per-project log dir is keyed by the cwd with '/' and '.'
# both replaced by '-'. e.g. /Users/x/.foo/bar -> -Users-x--foo-bar
encoded=$(printf '%s' "$PROJECT_DIR" | sed 's|[/.]|-|g')

# Claude Code stores logs under a per-platform cache root:
#   macOS : ~/Library/Caches/claude-cli-nodejs
#   Linux : ${XDG_CACHE_HOME:-~/.cache}/claude-cli-nodejs
# Probe the candidates and use the first that resolves. Exit cleanly if none
# exists (e.g. an unsupported platform) rather than silently no-op'ing on a
# hardcoded macOS path.
LOG_BASE=""
for cache_root in \
    "$HOME/Library/Caches/claude-cli-nodejs" \
    "${XDG_CACHE_HOME:-$HOME/.cache}/claude-cli-nodejs"; do
  if [ -d "$cache_root/${encoded}" ]; then
    LOG_BASE="$cache_root/${encoded}"
    break
  fi
done

[ -n "$LOG_BASE" ] || exit 0

declare -a missing_env
declare -a not_authorized        # parallel to not_authorized_urls
declare -a not_authorized_urls
declare -a auth_failed
declare -a other_failed

# MCP log dirs are named mcp-logs-plugin-<plugin>-<server>. Both plugin and
# server names can contain dashes, so we can't reliably split them from the
# glob alone — and hardcoding the plugin list breaks for installers who don't
# have every plugin. So we glob all plugin MCP log dirs and display the whole
# "<plugin>-<server>" remainder as the qualified identifier.
for log_dir in "$LOG_BASE"/mcp-logs-plugin-*; do
    [ -d "$log_dir" ] || continue
    qualified=$(basename "$log_dir")
    qualified="${qualified#mcp-logs-plugin-}"

    # Find the jsonl that contains our session_id (if any).
    session_log=$(grep -l "\"sessionId\":\"$session_id\"" "$log_dir"/*.jsonl 2>/dev/null | head -1)
    [ -n "$session_log" ] || continue

    # Look only at lines belonging to this session.
    session_lines=$(grep "\"sessionId\":\"$session_id\"" "$session_log" 2>/dev/null)
    [ -n "$session_lines" ] || continue

    if echo "$session_lines" | grep -q "Env file not found"; then
        missing_env+=("$qualified")
    elif echo "$session_lines" | grep -q "not authenticated for your user"; then
        # UC-proxy signature: the connection exists but the user hasn't OAuth'd.
        not_authorized+=("$qualified")
        url=$(echo "$session_lines" \
            | grep -oE 'https://[a-zA-Z0-9./_-]+/explore/connections/[a-zA-Z0-9_-]+' \
            | head -1)
        not_authorized_urls+=("${url:-<UI URL not captured>}")
    elif echo "$session_lines" | grep -q "Session terminated"; then
        # UC-proxy signature: expired Databricks CLI auth behind uc-mcp-proxy.
        auth_failed+=("$qualified")
    elif echo "$session_lines" | grep -qE "Connection failed|Connection closed"; then
        other_failed+=("$qualified")
    fi
done

total=$((${#missing_env[@]} + ${#not_authorized[@]} + ${#auth_failed[@]} + ${#other_failed[@]}))
[ "$total" -eq 0 ] && exit 0

# UC-proxy-specific failures drive whether we emit Databricks-flavored wording.
uc_total=$((${#not_authorized[@]} + ${#auth_failed[@]}))

echo "## ‼️ rpw MCP Health ‼️"
echo ""
echo "⚠️  Detected MCP failures in this session:"
echo ""
if [ ${#missing_env[@]} -gt 0 ]; then
    echo "  ❌ Missing env file — server has no credentials configured:"
    for s in "${missing_env[@]}"; do echo "    - plugin:$s"; done
fi
if [ ${#not_authorized[@]} -gt 0 ]; then
    echo "  🔐 UC connection not authenticated — needs OAuth in the Databricks UI:"
    # Group by URL (one connection can back multiple MCP servers) while
    # preserving first-seen order. Bash 3.2-compatible — no associative arrays.
    declare -a _seen_urls
    for i in "${!not_authorized_urls[@]}"; do
        url="${not_authorized_urls[$i]}"
        dup=0
        for u in "${_seen_urls[@]}"; do
            [ "$u" = "$url" ] && dup=1 && break
        done
        [ "$dup" -eq 1 ] && continue
        _seen_urls+=("$url")

        echo "    Open: $url"
        for j in "${!not_authorized[@]}"; do
            if [ "${not_authorized_urls[$j]}" = "$url" ]; then
                echo "      - plugin:${not_authorized[$j]}"
            fi
        done
    done
    unset _seen_urls
fi
if [ ${#auth_failed[@]} -gt 0 ]; then
    echo "  🔒 UC-proxy session terminated — likely expired Databricks CLI auth:"
    for s in "${auth_failed[@]}"; do echo "    - plugin:$s"; done
fi
if [ ${#other_failed[@]} -gt 0 ]; then
    echo "  ❌ Other connection failures:"
    for s in "${other_failed[@]}"; do echo "    - plugin:$s"; done
fi

echo ""
echo "---"
echo "‼️ ACTION REQUIRED ‼️ — this is an unprompted health notice you must surface to the user."
echo ""
echo "In your very next response to the user, before answering whatever else they asked:"
echo "  1. Lead with an eye-catching emoji header (e.g. ‼️ or ⚠️) so the user actually notices."
echo "  2. Briefly list the failing MCP servers above (one short line per category)."
echo "  3. PRIMARY OFFER: ask whether the user wants help repairing MCP config. Point them at"
echo "     the rpw-published:mcp-setup skill (and the plugin README) as the unified entry point"
echo "     — it walks through provisioning env files and any per-server credentials."
if [ "$uc_total" -gt 0 ]; then
    echo "  4. SECONDARY HELPERS (Databricks UC-proxy servers only) — include for convenience,"
    echo "     but do not lead with these:"
    if [ ${#not_authorized[@]} -gt 0 ]; then
        echo "     - For UC-connection-not-authenticated servers: render each 'Open:' URL as a"
        echo "       clickable markdown link and mention they can open it directly if they prefer."
    fi
    if [ ${#auth_failed[@]} -gt 0 ]; then
        echo "     - For UC-proxy-session-terminated servers: include the exact"
        echo "       \`databricks auth login --profile <profile>\` command they can run instead."
    fi
    echo "  5. Do NOT auto-invoke any fix (including /mcp-setup). Wait for user confirmation."
else
    echo "  4. Do NOT auto-invoke any fix (including /mcp-setup). Wait for user confirmation."
fi
echo ""
echo "If the user has not yet asked anything, still lead with this offer."
echo "If they declined the repair offer earlier in this session, do not re-prompt."

exit 0
