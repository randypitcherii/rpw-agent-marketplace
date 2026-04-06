---
name: rpw-building-doctor
description: Validate your development environment — checks all required tools and offers install help. Start here.
aliases:
  - getting-started
  - start-here
---

# /doctor - Development Environment Health Check

Validate that all tools expected by the rpw-building plugin are installed and working. This is the recommended first command for new users.

Treat everything typed after `/doctor` as optional context; the command behavior is fixed.

## Execution

Spawn a subagent using the **Agent tool** to perform all diagnostic checks. This keeps the parent conversation clean — only the final summary comes back.

Use the Agent tool with the following prompt:

---

**Subagent prompt (pass this entire block as the Agent tool's `prompt` parameter):**

```
You are a development environment doctor. Run every check below, gather all output, then return ONLY a concise summary. Do not ask the user any questions — just run the checks and report.

## Tool Checklist

Run each check command, capture exit code and version output.

### Required Tools

| Tool | Check Command | Purpose | Install Help |
|------|--------------|---------|--------------|
| `git` | `git --version` | Version control | https://git-scm.com/downloads |
| `make` | `make --version` | Build automation (Makefile-first workflow) | Xcode CLT: `xcode-select --install` |
| `uv` | `uv --version` | Python package management (replaces pip/venv) | `curl -LsSf https://astral.sh/uv/install.sh | sh` |
| `claude` | `claude --version` | Claude Code CLI | `npm install -g @anthropic-ai/claude-code` |

### Recommended Tools

| Tool | Check Command | Purpose | Install Help |
|------|--------------|---------|--------------|
| `bd` (beads) | `bd --version` | Git-backed issue tracking | `claude plugin install beads` |
| `cmux` | `cmux --version` | Terminal multiplexer for AI agents | https://cmux.dev |
| `node` | `node --version` | Node.js runtime (needed by claude CLI) | https://nodejs.org or `brew install node` |
| `superpowers` | `claude plugin list | grep superpowers` | Core skills (TDD, debugging, collaboration) | `claude plugin install superpowers` |

## Steps

1. **Check each tool** by running its check command. Capture exit code and version output.

2. **Required plugin installation check**: Verify that required external plugins are installed and enabled:
   - Run `claude plugin list` and check that `superpowers` appears in the output.
   - If missing, note: `claude plugin install superpowers`
   - Run `uv run python scripts/enable_required_stack.py --dry-run` to verify the full required stack is enabled. If any are missing, note this.

3. **MCP server check**: Verify that MCP servers referenced in the plugin have their `.env` files configured (check for `.env` existence in each `mcp-servers/` subdirectory).

4. **Plugin freshness check**: Compare installed plugin versions against the marketplace manifest.
   - Read `.claude-plugin/marketplace.json` from the repo to get latest available versions for each plugin.
   - For each plugin in the required stack (`rpw-building`, `rpw-working`, `rpw-databricks`), read its `plugin.json` version field.
   - Compare the installed version against the marketplace version.
   - If any plugin is outdated or version cannot be determined, also inspect the cache directory at `~/.claude/plugins/cache/rpw-agent-marketplace/` to confirm which versions are actually cached on disk. Compare cached file contents against the source repo to diagnose staleness.

5. **cmux integration check** (if cmux is installed):
   - Verify `CMUX_WORKSPACE_ID` or `CMUX_SURFACE_ID` env vars are set (indicates running inside cmux)
   - Check socket at `/tmp/cmux.sock` is accessible
   - If cmux MCP server is configured, verify connectivity with a `system.ping`

## Output Format

Return your findings in this exact structure:

### Tool Status
```
Tool        Status       Version
────        ──────       ───────
git         ✓ installed  2.43.0
make        ✓ installed  GNU Make 3.81
...
```

### Plugin Freshness
```
Plugin          Installed        Latest           Status
──────          ─────────        ──────           ──────
rpw-building    2026.03.0701     2026.03.0701     ✓ up to date
...
```

### Actions Needed
- List any missing tools with their install command/URL
- List any outdated plugins with update instructions
- List any missing .env files for MCP servers
- List any missing plugins from the required stack

If outdated plugins are found, include these update instructions:
- `claude plugin marketplace add rpw-agent-marketplace`
- Or delete cache and reinstall: `rm -rf ~/.claude/plugins/cache/rpw-agent-marketplace`

### Plugin Cache Behavior (include only if freshness issues are found)

Claude Code caches plugin files at install time in `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`. It does **not** read live from the source directory — changes to source files are invisible until the version is bumped and plugins are reinstalled.

The cache is keyed by version string only. If the version string stays the same, Claude Code will not refresh the cached files, even if the source has changed.

To fix outdated plugins:
1. Bump the version in `marketplace.json` and all `plugin.json` files.
2. Then run these commands in a **new session**:
   ```
   /plugin marketplace update rpw-agent-marketplace
   /plugin install rpw-building@rpw-agent-marketplace
   /plugin install rpw-working@rpw-agent-marketplace
   /plugin install rpw-databricks@rpw-agent-marketplace
   ```

### Summary
Print a one-line health summary (e.g., "6/7 tools installed, 3/3 plugins up to date, 1 action needed").
```

---

After the subagent returns, present its summary to the user. If the summary lists actions needed, ask the user if they'd like help with any of them before proceeding.

## Scope and Safety

- This command is read-only — it checks state but does not modify anything.
- Install actions require explicit user confirmation before execution.
- Do not modify `.env` files, settings, or git state.
