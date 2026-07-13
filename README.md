# rpw-agent-marketplace

A [Claude Code](https://docs.claude.com/en/docs/claude-code) plugin marketplace by
Randy Pitcher — build workflows, MCP standards, environment setup, and a set of
generic productivity skills and MCP servers.

> This is the public mirror. It ships the `rpw-published` plugin only; internal
> tooling is kept in a separate private repository.

## Install

```bash
claude plugin marketplace add randypitcherii/rpw-agent-marketplace
claude plugin install rpw-published@rpw-agent-marketplace
```

Then run `/doctor` (or `/getting-started`) to validate your environment — it checks
required host CLIs, MCP config health, and plugin freshness, with next actions for
anything missing.

## What's in `rpw-published`

- **`/build`** — a full lifecycle build workflow (a thin Claude Code adapter over a
  harness-neutral LangGraph runtime).
- **MCP servers** — generic, secret-free servers (Google Docs/Drive/Gmail/Tasks,
  Gemini image, Jira, Exa web search, iMessage) that resolve credentials from your
  own environment at startup.
- **Skills** — productivity and engineering skills: research, visualization,
  document handling, Databricks workflows, TDD, systematic debugging, and more.
- **Standards** — MCP authoring standards, `uv`-based Python workflow, calendar-first
  versioning, and environment-file conventions.

## Updating

Re-run the install command to pull the latest plugin versions:

```bash
claude plugin marketplace update rpw-agent-marketplace
```

The `/doctor` command includes a freshness check that warns when an installed
version is behind the marketplace.

## License

See [`LICENSE`](./LICENSE).
