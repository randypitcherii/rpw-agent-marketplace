---
name: code-review-and-pr
description: House conventions for reviewing a diff/PR and preparing a PR for merge in this repo. Use when the user says "prep this PR", "review this diff", "review this PR", "ready to merge?", "is this mergeable?", or before opening/landing a PR. Carries the repo-specific review checklist and PR-body shape; defers review *mechanics* to the built-in /code-review, /review, and /security-review commands.
---

# Code Review + PR Preparation (House Conventions)

This skill is the **conventions layer** for two moments: reviewing a change, and preparing it to merge. It does **not** re-implement diff analysis — the harness already ships that. Compose:

| Need | Use this (mechanics) | This skill adds (conventions) |
|------|----------------------|-------------------------------|
| Find correctness bugs + reuse/simplification/efficiency cleanups in the diff | `/code-review` (`--comment` to post inline, `--fix` to apply) | The repo-specific things to look for that a generic tool can't know |
| Review an open PR | `/review` | What "ready to merge" means *here* |
| Security pass on pending changes | `/security-review` | Marketplace secret/invariant rules below |

**Rule of thumb:** run the harness command for the *mechanics*, then walk the conventions below for what the mechanics don't encode. If a finding is generic ("this loop is O(n²)"), the harness command owns it. If it's repo-specific ("this leaks a Claude-ism into runtime code"), it lives here.

> **Harness-neutral by design.** This skill is plain guidance, not Claude-CLI-specific. The deepagent build graph's review step (#243) and the cross-harness skill distribution (#253) load it as a reviewer rubric. Keep additions phrased as conventions a reviewer applies, not as slash-command invocations — name the command as *one* way to get the mechanics, never the only way.

---

## Part 1 — Reviewing a diff or PR

Run `/code-review` first for the generic pass. Then check these **repo-specific** dimensions the generic pass won't know about:

### 1. Receipt / gate contracts
- `/build` phases are enforced by **receipts** (`.rpw/build/receipts/<phase>.json`) and the build-completion-gate Stop hook. The gate checks **receipt existence + valid JSON, not contents** — so a change that makes a gate conditional is a **`build.md` prose edit plus an auto-written receipt**, not a hook change. Flag any PR that tries to gate behavior by editing the hook when prose+receipt is the real lever.
- A runtime change that claims a phase passed must reflect the *actual* gate: runtime receipts must mirror `make runtime-test`, and `eval-test` stays a separate target on purpose. Don't let a receipt assert coverage the test target didn't run.

### 2. Harness-neutral boundaries (no Claude-isms in runtime code)
- `libs/rpw_runtime` is the **canonical, harness-neutral runtime**. `plugin.json` / marketplace are a thin Claude *convenience adapter* over it. Flag any Claude-CLI-specific assumption (slash-command names, `${CLAUDE_PLUGIN_ROOT}`, `.claude/` paths, Claude-only tool names) that leaks **into** `libs/`. Adapters may know about Claude; the runtime must not.
- Lifecycle belongs in the graph; coordination (the claim ledger, `rpw` coordination surface) is a *separate* surface, **not** graph hooks. A PR that wires coordination into lifecycle hooks is crossing a boundary — flag it.

### 3. Custom ChatModel wrappers → demand a live routing check
- Custom `BaseChatModel` wrappers (LLM pool, CLI providers) repeatedly hit **langchain-unrecognized-class** bugs that fake-member unit tests cannot catch — literal `tool_choice=None` forwarding, `max_retries` not threaded, etc. If a PR adds or edits such a wrapper, the review is **not complete on unit tests alone**: require evidence of a cheap **live routing call** (one real round-trip through the wrapper). "Unit tests pass" is insufficient here; say so.

### 4. Skill / command drift
- Skills are auto-discovered from `plugins/*/skills/`. When a PR changes a skill's behavior, check the **frontmatter `description`** (the trigger surface) still matches what the body does, and that any `AGENTS.md` / `CLAUDE.md` skill list or README catalog stays in sync. Drift between the description and the body is a real defect — the description is what decides whether the skill ever loads.
- Same for `/build` and other commands: a behavior change in `build.md` that isn't reflected in its phase docs/receipts is drift.

### 5. Marketplace invariants
- Marketplace name stays `rpw-agent-marketplace`; plugin entries use `source: "./plugins/<name>"`; plugins live under `./plugins/`.
- **No secrets committed** — `.env` files, tokens, credentials. The Databricks-proxy `uv.lock` files are gitignored on purpose (wrong URLs for public consumers); only the eval-harness lock stays pinned. Flag any committed lockfile pinning the proxy URL into a shared path.
- After structural moves, stale legacy artifacts (moved-path caches, venvs, `__pycache__`) must be removed.

### 6. Tests prove the real path
- Bug fixes need a **red→green** test: a test that failed before the fix and passes after. Flag a "fix" with no test that demonstrates the failure mode.
- The test must exercise the **full path the user hits** — if the flow crosses a proxy/router/multiple hops, an isolated unit test of the new function is not enough.

---

## Part 2 — Preparing a PR

Run `/security-review` on the pending changes, fix anything critical, then shape the PR per the conventions below.

### Commit hygiene is squash-merge-aware
PRs here are **squash-merged** — individual commit boundaries collapse into one commit at merge time. So:
- **Don't over-engineer commit granularity.** Don't split a coherent change into ceremonial micro-commits or stall asking "one commit or several?" — it's friction with no downstream effect.
- A coherent unit of work = one commit is the default. Keep messages thoughtful anyway (the squash commit borrows from them), and **always** end with the trailer:
  ```
  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

### PR body shape: What / Why / Verification
Every PR body uses these three sections. No "smoke test", no "sanity check" — **name the actual check that ran.**

```markdown
## What
<the change, in plain terms — what's new/fixed/removed>

## Why
<the motivation — the problem, the issue it advances, the decision behind it>

## Verification
<the specific checks that ran and their results — name them>
- `make check` → green (N tests, 0 failed)
- ran the script once against a real input → produced expected X
- hit the endpoint → 200 with expected body
- live routing call through the new wrapper → returned a valid completion
```

**Banned vocabulary** (anywhere a human reads — PR body, test plan, retro):
- ❌ "smoke test", "sanity check", "quick test" — they hide *what* was verified and at what commitment level.
- ✅ Say the action: "ran the script once against a real input", "loaded the page and confirmed it renders", "confirmed the endpoint returns 200".

### Issue linkage: advance vs. close (#212)
Pick the trailer keyword by whether this PR **fully closes** the issue:
- **Closes the issue** → `Closes #N`. The issue closes on merge.
- **Advances a multi-PR issue** (other checklist items owned by sibling issues/PRs) → `Part of #N` or `Advances #N`. The issue **stays open**; tick its completed checklist items. Only the PR that lands the *last* open item uses `Closes`.

When in doubt, check the issue body for sibling-issue references before choosing the keyword — closing an umbrella issue early loses the remaining work.

### "Ready to merge?" checklist
Before opening — or when asked "is this mergeable?" — confirm:
- [ ] `make check` (the project gate) is green. Name the result in **Verification**.
- [ ] PR body has **What / Why / Verification**; Verification names real checks (no banned vocab).
- [ ] Issue trailer is correct (`Closes` vs `Part of` — see above).
- [ ] `Co-Authored-By: Claude` trailer present on the commit(s).
- [ ] No secrets / proxy-pinned lockfiles / out-of-scope files in the diff.
- [ ] Repo-specific review dimensions (Part 1) walked for anything they apply to.
- [ ] Branch targets the integration branch (`production`), not a release/publish branch.

### Merge autonomy boundary
Routine feature PRs to `production` are delivered autonomously — push, open, squash-merge, clean up — **no confirmation needed**. **Confirm first only** when the action triggers a public release (`make publish-public` / merging the publish PR on the mirror), it's a `--force`-push to a shared branch, or the working tree mixes unrelated concerns. When a build runs under an orchestrator that serializes sibling merges, **open the PR and stop** — let the orchestrator drive the merge and resolve any `plugin.json` version-line conflicts; do not rebase against sibling PRs.

---

## Quick reference

```
Reviewing?   /code-review (mechanics) → walk Part 1 repo-specific dimensions
Security?    /security-review (mechanics) → check marketplace invariants
Preparing?   What/Why/Verification body · name real checks · Co-Authored-By · Closes vs Part-of
Mergeable?   make check green · body shape · issue trailer · no secrets · base = production
```
