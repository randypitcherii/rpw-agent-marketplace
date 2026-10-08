---
name: rpw-published-doctor
description: Validate the tools required by the public RPW plugin and offer install help.
aliases:
  - getting-started
  - start-here
---

# /doctor — public plugin health check

Validate a fresh RPW Marketplace installation without assuming the source monorepo or any private plugin exists.

Treat everything typed after `/doctor` as optional context. Run read-only checks yourself; do not ask the user to paste command output.

## Checks

Capture the exit code and version for each command:

| Tool | Check | Required for | Install help |
|---|---|---|---|
| `git` | `git --version` | Version control and worktrees | <https://git-scm.com/downloads> |
| `gh` | `gh --version` and `gh auth status` | Issues, claims, and pull requests | <https://cli.github.com> |
| `claude` | `claude --version` | Plugin commands and shipped agents | `npm install -g @anthropic-ai/claude-code` |
| `uv` | `uv --version` | Python-based skills and MCP servers | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| `node` | `node --version` | Claude Code and JavaScript skills | <https://nodejs.org> |
| `make` | `make --version` | Repositories whose gate uses Make | Xcode CLT: `xcode-select --install` |

Then run:

```bash
claude plugin marketplace list
claude plugin list
```

Confirm that:

- marketplace `rpw-agent-marketplace` is registered;
- plugin `rpw-published@rpw-agent-marketplace` is enabled;
- the installed plugin reports no load error.

`chrome-devtools-mcp` is optional. Report it as optional and absent unless browser automation is requested; never mark the RPW plugin unhealthy only because it is missing.

## Output

Present:

1. a compact tool table with `ok`, `missing`, or `auth needed`;
2. marketplace and plugin status;
3. one-line overall verdict;
4. an **Actions needed** list with exact install or login commands.

Do not claim to inspect an unpublished runtime, private plugin, or MCP credential store. Ask before running any install, login, or settings-changing command.

## Cache recovery

If the plugin is installed but stale or failed to load, recommend this in a new session:

```text
/plugin marketplace update rpw-agent-marketplace
/plugin install rpw-published@rpw-agent-marketplace
```

Claude Code caches plugins by marketplace, plugin name, and version. If reinstalling the same version does not refresh it, uninstall that plugin version first, then install it again. Do not delete unrelated cache directories.
