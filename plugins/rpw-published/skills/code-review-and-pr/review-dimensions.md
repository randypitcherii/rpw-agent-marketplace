# Repo-specific review dimensions

Companion to [SKILL.md](SKILL.md) Part 1 (#1605 split; the #531 pattern). Run
`/code-review` (or any equivalent mechanics pass) **first** for the generic
findings, then walk these — each one encodes a boundary a generic tool cannot
know about, and each was earned from a real defect that shipped.

## 1. Receipt / gate contracts

- `/build` phases are enforced by **receipts** (`.rpw/build/receipts/<phase>.json`) the graph writes itself — there is no Stop-hook gate any more (#515 deleted the ritual-era `build-completion-gate.sh` / `build-compliance.sh`). Making a gate conditional is a **`build.md` prose edit plus an auto-written receipt**. Flag any PR that reintroduces a harness hook as the enforcement point: harness hooks never reach the runtime's subprocess shell, so they can't gate a graph-driven build.
- A runtime change that claims a phase passed must reflect the *actual* gate: runtime receipts must mirror `make runtime-test`, and `eval-test` stays a separate target on purpose. Don't let a receipt assert coverage the test target didn't run.

## 2. Harness-neutral boundaries (no Claude-isms in runtime code)

- `libs/rpw_runtime` is the **canonical, harness-neutral runtime**. `plugin.json` / marketplace are a thin Claude *convenience adapter* over it. Flag any Claude-CLI-specific assumption (slash-command names, `${CLAUDE_PLUGIN_ROOT}`, `.claude/` paths, Claude-only tool names) that leaks **into** `libs/`. Adapters may know about Claude; the runtime must not.
- Lifecycle belongs in the graph; coordination (the claim ledger, `rpw` coordination surface) is a *separate* surface, **not** graph hooks. A PR that wires coordination into lifecycle hooks is crossing a boundary — flag it.

## 3. Custom ChatModel wrappers → demand a live routing check

- Custom `BaseChatModel` wrappers (LLM pool, CLI providers) repeatedly hit **langchain-unrecognized-class** bugs that fake-member unit tests cannot catch — literal `tool_choice=None` forwarding, `max_retries` not threaded, etc. If a PR adds or edits such a wrapper, the review is **not complete on unit tests alone**: require evidence of a cheap **live routing call** (one real round-trip through the wrapper). "Unit tests pass" is insufficient here; say so.

## 4. Skill / command drift

- Skills are auto-discovered from `plugins/*/skills/`. When a PR changes a skill's behavior, check the **frontmatter `description`** (the trigger surface) still matches what the body does, and that any `AGENTS.md` / `CLAUDE.md` skill list or README catalog stays in sync. Drift between the description and the body is a real defect — the description is what decides whether the skill ever loads.
- Same for `/build` and other commands: a behavior change in `build.md` that isn't reflected in its phase docs/receipts is drift.
- A SKILL.md that outgrows the word cap is drift too: move bulk into companion `*.md` files beside it and keep SKILL.md the decision surface, rather than raising the cap.

## 5. Marketplace invariants

- Marketplace name stays `rpw-agent-marketplace`; plugin entries use `source: "./plugins/<name>"`; plugins live under `./plugins/`.
- **No secrets committed** — `.env` files, tokens, credentials. The Databricks-proxy `uv.lock` files are gitignored on purpose (wrong URLs for public consumers); only the eval-harness lock stays pinned. Flag any committed lockfile pinning the proxy URL into a shared path.
- After structural moves, stale legacy artifacts (moved-path caches, venvs, `__pycache__`) must be removed.

## 6. Tests prove the real path

- Bug fixes need a **red→green** test: a test that failed before the fix and passes after. Flag a "fix" with no test that demonstrates the failure mode.
- The test must exercise the **full path the user hits** — if the flow crosses a proxy/router/multiple hops, an isolated unit test of the new function is not enough.
- A test that passes locally but fails in CI is **not** a CI problem by default — it is usually a hermeticity defect: the test reads host env, ambient files, or real service state the CI host happens to set. Fix by controlling the inputs explicitly (monkeypatch/env isolation), not by loosening the assertion.
