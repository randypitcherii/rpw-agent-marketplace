# rpw-agent-marketplace

A [Claude Code](https://docs.claude.com/en/docs/claude-code) plugin marketplace by
Randy Pitcher. It ships one plugin — **`rpw-published`** — bundling a full build
workflow, 65 skills, 8 subagents, 13 commands, and 8 MCP servers.

These are the tools I use every day, published as-is. They lean toward Python/`uv`,
Google Workspace, and Databricks, because that is what I work in. Take the parts that
fit.

> **About this repo.** It is a public mirror of a private repository. Only the
> `rpw-published` plugin is mirrored here; internal tooling stays private. Content
> arrives through reviewed sync PRs, so changes committed here directly would be
> overwritten — please open an issue rather than a pull request.

## Install

The only requirement to install is Claude Code itself:

```bash
claude plugin marketplace add randypitcherii/rpw-agent-marketplace
claude plugin install rpw-published@rpw-agent-marketplace
```

For the optional Chrome DevTools MCP server, install its official plugin separately:

```bash
claude plugin marketplace add anthropics/claude-plugins-official
claude plugin install chrome-devtools-mcp@claude-plugins-official
```

Then run **`/doctor`** (aliased `/getting-started`). It checks your host CLIs, MCP
server health, and plugin freshness, and lists a next action for anything missing.
It is the recommended first command.

## What's in `rpw-published`

**Commands**

- **`/build`** — a full lifecycle build workflow: plan, dispatch parallel workers in
  git worktrees, verify, review, and open a PR. It is a thin Claude Code adapter over
  a harness-neutral LangGraph runtime, so the same graph can run outside Claude Code.
- **`/doctor`** — environment and MCP health check.
- **`/code-mode`** — a lighter implementation-first loop with explicit safety and
  verification gates, for when `/build` is more ceremony than the task deserves.
- **`/ship-it`**, **`/where-were-we`**, **`/task-setup`**, **`/feedback`**,
  **`/project-feedback`**, **`/plugin-feedback`**, **`/required-stack`**,
  **`/activity-context`** — session and repo housekeeping.

**Skills** (65) — loaded automatically when a task matches. Highlights:

- *Engineering practice* — `tdd`, `systematic-debugging`, `code-review-and-pr`,
  `subagent-dispatch`, `wave-supervisor` (multi-issue parallel orchestration).
- *Standards* — `mcp-standards`, `python-with-uv`, `versioning-standards`,
  `env-preferences`.
- *Databricks* — `databricks-jobs`, `databricks-apps`, `databricks-model-serving`,
  `databricks-uc-connections`.
- *Productivity* — `image-generation` (responsive parallel image batches), `diagram`
  (styled HTML-to-PNG diagrams), `dataviz` (charts, plots, dashboards), `document-files`
  (PDF/docx/xlsx/pptx), `doc-styling`, `slack-formatting`, `human-todo`,
  `changelog-release-notes`, `dispatch-launch`, `mobile-sso` (CLI login from a phone),
  `omnigent-chief-of-staff` (triage and bulk-manage a fleet of agent sessions).

**Subagents** (8) — `build-worker`, `reviewer`, `research-lead`,
`research-worker`, `debug-lead`, `privacy-reviewer`, `project-manager`, `minion`.

**MCP servers** (8, plus one dependency) — all served through one `rpw` MCP entry, so
they appear as `mcp__plugin_rpw-published_rpw__<tool>`. Ask the `rpw_backends` tool which
servers came up and why any did not.

| Server | What it does |
|---|---|
| `google-docs` | Google Docs, Sheets, and Slides — read, write, format, template fill |
| `google-drive` | File listing and metadata |
| `google-gmail` | Search, read, send |
| `google-calendar` | List calendars, read and create events |
| `google-tasks` | Task lists and tasks |
| `gemini-image` | Image generation and editing via Gemini on Vertex AI |
| `jira` | Issue search, read, create, comment, transition |
| `exa` | Web search and fetch (hosted, streamable HTTP) |
| `chrome-devtools` | Optional browser automation and debugging from the separately installed `claude-plugins-official` marketplace |

**Without Claude Code:** any MCP client on a host with [`uv`](https://docs.astral.sh/uv/)
can run all of these servers as one stdio server:

```json
{"mcpServers": {"rpw": {"command": "uvx", "args": ["--from",
  "git+https://github.com/randypitcherii/rpw-agent-marketplace#subdirectory=plugins/rpw-published",
  "rpw-mcp"]}}}
```

## Prerequisites

Skills and commands need nothing beyond Claude Code. The MCP servers have their own
requirements — install only what you plan to use:

| To use | You need |
|---|---|
| The Python servers (Google ×5, Gemini, Jira) | [`uv`](https://docs.astral.sh/uv/) |
| `chrome-devtools` | Node.js (for `npx`) |
| The Google servers and `gemini-image` | A Google Cloud project with the relevant APIs enabled, then `gcloud auth application-default login` |
| `jira` | Your Jira host and an API token |

**No secrets live in this repo or in your plugin directory.** Each Python server reads
an env file from `~/.claude/mcp-servers/<server>/dev.env` and resolves credentials at
startup — the Google servers and `gemini-image` mint short-lived tokens from gcloud
Application Default Credentials, so nothing sensitive is written to disk. Every server
ships a `template.env` documenting its variables; copy it to `dev.env` and fill in the
non-secret IDs.

The **`/mcp-setup`** skill automates this. Fair warning: it prefers Databricks-backed
credential sources (Unity Catalog connections, Databricks secret scopes) because that
is my environment. If you are not on Databricks, decline that path and it falls back
to plain env files, which work fine.

## Updating

```bash
claude plugin marketplace update rpw-agent-marketplace
```

`/doctor` includes a freshness check that warns when an installed plugin is behind the
marketplace.

## Versioning and releases

Versions are calendar-first: `YYYY.MM.DDNN` — for example `2026.07.1301`, the first
release cut on 2026-07-13. Each published update gets a
[GitHub Release](https://github.com/randypitcherii/rpw-agent-marketplace/releases)
summarizing what changed.

## License

[Apache-2.0](./LICENSE).
