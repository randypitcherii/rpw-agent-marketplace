# rpw-agent-marketplace

- Marketplace manifest is `./.claude-plugin/marketplace.json`; marketplace name must remain `rpw-agent-marketplace`.
- Use `metadata.pluginRoot: "./plugins"` and keep plugin directories under `./plugins/`.
- In marketplace plugin entries, use `source: "./plugins/<plugin-name>"` (CLI-compatible for `claude plugin marketplace add`).
- Scope: `plugins/rpw-working` is for improving day-to-day human work activities and operating workflows.
- Scope: `plugins/rpw-databricks` is for Databricks-specific field work activities.
- Scope: `plugins/rpw-building` is for agentic software development workflows.
- Validate repo invariants with: `uv run python -m unittest tests.test_repo_validations -v`.
- For non-interactive marketplace ops, use `claude plugin marketplace add|list|remove|update` and `claude plugin install|uninstall`.
- After structural moves, remove stale legacy artifacts (moved-path caches/venvs/pycache) and re-run tests.
- `.env` files contain secrets — never commit them. OK to create or edit `.env` files when the user confirms, but always confirm before each modification.
