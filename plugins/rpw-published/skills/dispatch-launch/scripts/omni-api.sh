# shellcheck shell=bash
# Shared Omnigent REST plumbing for the dispatch-launch scripts (#1613, #2030).
# Source it; do not execute it. It sets API_BASE and AUTH_HEADERS and defines
# `api` and `die`.
#
#   source "$(dirname "${BASH_SOURCE[0]}")/omni-api.sh"
#   out="$(api GET "/v1/sessions/$SID")"
#   code="${out##*$'\n'}"; payload="${out%$'\n'*}"
#
# env:
#   OMNIGENT_API_BASE          override the API base URL
#   RUNNER_SERVER_URL          server base, injected in omnigent sessions
#   OMNIGENT_CONFIG            omnigent config (default ~/.omnigent/config.yaml);
#                              its `server:` line is the next fallback
#   OMNIGENT_API_TOKEN         bearer token; otherwise `databricks auth token`
#   OMNIGENT_WORKSPACE_HOST    workspace that mints the token (default: the
#                              server's own host, or the `omnigent login`
#                              pointer for a Databricks App server)
#   OMNIGENT_PROFILE           databricks profile (default: the ~/.databrickscfg
#                              profile whose host is the workspace, DEFAULT
#                              first; else the host's first DNS label)
#   OMNIGENT_RUNNER_SLICE_KEY  host id for the shard header, injected in sessions

die() { printf '%s\n' "$1" >&2; exit "${2:-1}"; }

# --- base URL ---------------------------------------------------------------
# Explicit override first, then the server base every omnigent session gets,
# then the `server:` default `omnigent login` records, then the local host
# service. Hardcoding the localhost port is the trap: on a managed server
# nothing listens there (#2030). The server URL is never a literal here: the
# omnigent config is its one runtime home (#2093).
_omni_configured_server() {
  local cfg="${OMNIGENT_CONFIG:-$HOME/.omnigent/config.yaml}"
  [[ -r "$cfg" ]] || return 0
  sed -n -E 's/^server:[[:space:]]*["'"'"']?([^"'"'"'[:space:]]+).*$/\1/p' "$cfg" | head -n 1
}
API_BASE="${OMNIGENT_API_BASE:-${RUNNER_SERVER_URL:-}}"
[[ -n "$API_BASE" ]] || API_BASE="$(_omni_configured_server)"
[[ -n "$API_BASE" && "$API_BASE" != "null" ]] || API_BASE="http://127.0.0.1:6767"
API_BASE="${API_BASE%/}"

# Workspace that mints the bearer. A workspace-mounted server (`.../api/2.0/
# omnigent`) is its own workspace; a Databricks App is not, so its workspace
# comes from the pointer record `omnigent login` stored for it.
_omni_workspace_host() {
  if [[ -n "${OMNIGENT_WORKSPACE_HOST:-}" ]]; then
    printf '%s\n' "${OMNIGENT_WORKSPACE_HOST%/}"; return
  fi
  if [[ "$API_BASE" == */api/* ]]; then
    printf '%s\n' "${API_BASE%%/api/*}"; return
  fi
  local tokens="${OMNIGENT_AUTH_TOKENS:-$HOME/.omnigent/auth_tokens.json}"
  local pointed=""
  if [[ -r "$tokens" ]]; then
    pointed="$(python3 -c 'import json,sys
rec = json.load(open(sys.argv[1])).get(sys.argv[2]) or {}
print(rec.get("workspace_host") or "")' "$tokens" "$API_BASE" 2>/dev/null || true)"
  fi
  printf '%s\n' "${pointed:-$API_BASE}"
}

# The ~/.databrickscfg profile whose `host` is $1 — DEFAULT when it matches,
# else the first match; empty when none does.
_omni_profile_for_host() {
  local cfg="${DATABRICKS_CONFIG_FILE:-$HOME/.databrickscfg}"
  [[ -r "$cfg" ]] || return 0
  python3 - "$cfg" "$1" 2>/dev/null <<'PY' || true
import configparser, sys
cfg = configparser.ConfigParser(interpolation=None)
cfg.read(sys.argv[1])
want = sys.argv[2].rstrip("/").lower()
def host(section):
    return (section.get("host") or "").rstrip("/").lower()
names = [n for n in cfg.sections() if host(cfg[n]) == want]
if host(cfg[cfg.default_section]) == want:
    names.insert(0, "DEFAULT")
print(names[0] if names else "")
PY
}

# --- auth -------------------------------------------------------------------
# The local host service needs none. The managed server needs a workspace
# bearer token, and the sharded deployment wants the host id as a shard hint or
# it can answer `wrong_replica` from the wrong replica.
AUTH_HEADERS=()
case "$API_BASE" in
  http://127.0.0.1*|http://localhost*) ;;
  *)
    token="${OMNIGENT_API_TOKEN:-}"
    if [[ -z "$token" ]]; then
      command -v databricks >/dev/null 2>&1 ||
        die "no OMNIGENT_API_TOKEN and no databricks CLI to mint one for $API_BASE" 3
      host="$(_omni_workspace_host)"
      # `--profile` is mandatory: a bare --host is ambiguous whenever DEFAULT
      # points at the same workspace, which is the common local setup.
      profile="${OMNIGENT_PROFILE:-${DATABRICKS_CONFIG_PROFILE:-}}"
      # A guessed name that is not a real profile only works while a host-keyed
      # cached token lasts, then fails for good — so prefer a real profile whose
      # host matches the workspace (#2093).
      [[ -n "$profile" ]] || profile="$(_omni_profile_for_host "$host")"
      if [[ -z "$profile" ]]; then
        bare="${host#*://}"
        profile="${bare%%.*}"
      fi
      token="$(databricks auth token --profile "$profile" --host "$host" 2>/dev/null |
                 python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])' 2>/dev/null || true)"
      [[ -n "$token" ]] ||
        die "could not mint a token for $host (profile '$profile'); set OMNIGENT_PROFILE or OMNIGENT_API_TOKEN" 3
    fi
    AUTH_HEADERS+=(-H "Authorization: Bearer $token")
    if [[ -n "${OMNIGENT_RUNNER_SLICE_KEY:-}" ]]; then
      AUTH_HEADERS+=(-H "X-Databricks-Omnigent-Slice-Key: ${OMNIGENT_RUNNER_SLICE_KEY}")
    fi
    ;;
esac

api() {  # api <METHOD> <PATH> [<json-body>]  -> body, newline, HTTP status
  local method="$1" path="$2"; shift 2
  local body=(); [[ $# -gt 0 ]] && body=(-d "$1")
  # bash 3.2 (macOS /bin/bash) errors on an empty array under `set -u`, so both
  # expansions use the ${arr[@]+…} guard rather than a bare "${arr[@]}".
  curl -sS -w $'\n%{http_code}' -X "$method" "${API_BASE}${path}" \
    ${AUTH_HEADERS[@]+"${AUTH_HEADERS[@]}"} -H 'Content-Type: application/json' \
    ${body[@]+"${body[@]}"}
}
