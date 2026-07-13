---
name: rpw-published-doctor
description: Validate your development environment — checks all required tools and offers install help. Start here.
aliases:
  - getting-started
  - start-here
---

# /doctor - Runtime & Environment Health Check

Validate that the runtime and the tools/plugins it expects are healthy. This is the
recommended first command for new users.

Treat everything typed after `/doctor` as optional context; the command behavior is fixed.

## What it reports

The **runtime doctor** (`rpw_runtime.doctor`, #153) owns the health report. Its core is
**harness-neutral** and works with no Claude plugin present:

- `runtime_version`, `graph_version`, `source_git_sha`
- `host_adapter` — `claude-code` / `cursor` / `headless` / `codex` / `opencode` / `unknown`
- **Required stack** status (`superpowers`, `code-context`, `context-mode`, `rpw-published`, `rpw-private`)
- **MCP health** — per-server config/env readiness (env-file presence + required key **names**; never values; no network)

When `host_adapter == claude-code`, it additionally attaches the **plugin-freshness**
add-on: per-plugin source vs marketplace vs newest-cached version, and the cache path.

## Execution

Run these steps yourself (read-only — do not modify settings, `.env`, or git state).

### 1. Run the runtime doctor

```bash
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
if [ -d "$ROOT/libs/rpw_runtime" ]; then
  ( cd "$ROOT/libs/rpw_runtime" && uv run python -m rpw_runtime.doctor --repo-root "$ROOT" )
else
  echo "runtime doctor unavailable here (no libs/rpw_runtime checkout) — running CLI-tool checks only"
fi
```

The doctor prints the report (runtime/provenance, host, required stack, MCP health,
plugin freshness when on Claude Code, and an **Actions Needed** list). Add `--json` for a
machine-readable record (suitable for receipts / eval traces). Pass `--host <name>` to
override host detection.

### 2. CLI tool checks (host-neutral)

The runtime doctor covers the runtime; these confirm the host toolchain. For each, capture
exit code + version:

| Tool | Check | Purpose | Install help |
|------|-------|---------|--------------|
| `git` | `git --version` | Version control | https://git-scm.com/downloads |
| `make` | `make --version` | Makefile-first workflow | Xcode CLT: `xcode-select --install` |
| `uv` | `uv --version` | Python package mgmt (runs the doctor) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `gh` | `gh --version` | GitHub CLI (issues/PRs) | https://cli.github.com |
| `node` | `node --version` | Node runtime (needed by `claude` CLI) | https://nodejs.org or `brew install node` |
| `claude` | `claude --version` | Claude Code CLI (only relevant on the claude-code host) | `npm install -g @anthropic-ai/claude-code` |

## Output

Present the runtime doctor's report, then the CLI-tool table, then a one-line health
summary (e.g. "runtime 0.1.0 · host claude-code · 2/5 stack · 9/10 MCP · 2/2 plugins fresh
· 6/7 tools"). If the **Actions Needed** list is non-empty, ask the user whether they'd
like help with any item before doing anything.

### Plugin cache behavior (mention only if freshness flags a `cache-stale` plugin)

Claude Code caches plugin files at `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`
and keys the cache by version string. If the version string is unchanged, the cache is not
refreshed even when source changes. To refresh a stale plugin, in a **new session**:

```
/plugin marketplace update rpw-agent-marketplace
/plugin install rpw-published@rpw-agent-marketplace
```

`rpw-private` is a native dependency of `rpw-published` and auto-installs.

## Scope and Safety

- Read-only — it inspects state but modifies nothing.
- The MCP health check reports env-file presence and required key **names** only — never
  secret values — and performs no network calls (live MCP reachability is out of scope).
- Install/enable actions require explicit user confirmation before execution.
- Do not modify `.env` files, settings, or git state.
