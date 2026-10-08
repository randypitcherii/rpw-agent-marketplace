---
name: code-review-and-pr
description: House conventions for reviewing a diff/PR and preparing a PR for merge in this repo. Use when the user says "prep this PR", "review this diff", "review this PR", "ready to merge?", "is this mergeable?", or before opening/landing a PR. Carries the repo-specific review checklist, the mandatory demo-at-creation gate, and the PR-body shape; defers review *mechanics* to the built-in /code-review, /review, and /security-review commands.
---

# Code Review + PR Preparation (House Conventions)

This skill is the **conventions layer** for two moments: reviewing a change, and preparing it to merge. It does **not** re-implement diff analysis — the harness already ships that. Compose:

| Need | Use this (mechanics) | This skill adds (conventions) |
|------|----------------------|-------------------------------|
| Find correctness bugs + reuse/simplification/efficiency cleanups in the diff | `/code-review` (`--comment` to post inline, `--fix` to apply) | The repo-specific things to look for that a generic tool can't know |
| Review an open PR | `/review` | What "ready to merge" means *here* |
| Security pass on pending changes | `/security-review` | Marketplace secret/invariant rules (dimension 5) |

**Rule of thumb:** run the harness command for the *mechanics*, then walk the conventions below for what the mechanics don't encode. If a finding is generic ("this loop is O(n²)"), the harness command owns it. If it's repo-specific ("this leaks a Claude-ism into runtime code"), it lives here.

> **Harness-neutral by design.** This skill is plain guidance, not Claude-CLI-specific. The deepagent build graph's review step (#243) and the cross-harness skill distribution (#253) load it as a reviewer rubric. Keep additions phrased as conventions a reviewer applies, not as slash-command invocations — name the command as *one* way to get the mechanics, never the only way.

---

## Part 1 — Reviewing a diff or PR

Run `/code-review` first for the generic pass. Then walk the six **repo-specific** dimensions in [`review-dimensions.md`](review-dimensions.md) — the boundaries a generic pass cannot know:

| # | Dimension | The failure it catches |
|---|-----------|------------------------|
| 1 | **Receipt / gate contracts** | a harness hook reintroduced as the `/build` enforcement point (#515); a receipt asserting coverage the test target never ran |
| 2 | **Harness-neutral boundaries** | a Claude-ism (slash-command name, `${CLAUDE_PLUGIN_ROOT}`, `.claude/` path) leaking **into** `libs/`; coordination wired into lifecycle hooks |
| 3 | **Custom ChatModel wrappers** | a langchain-unrecognized-class bug fake-member unit tests can't see — demand evidence of one cheap **live routing call** |
| 4 | **Skill / command drift** | frontmatter `description` no longer matching the body (it decides whether the skill loads at all); catalogs out of sync; a SKILL.md past the word cap |
| 5 | **Marketplace invariants** | committed secrets or a proxy-pinned lockfile; marketplace name / `source:` shape broken; stale artifacts after a structural move |
| 6 | **Tests prove the real path** | a "fix" with no red→green test; a unit test standing in for the full path the user hits; a CI-only failure treated as a CI problem instead of a hermeticity defect |

Read the companion before signing off on anything those dimensions touch — the table rows are triggers, not the rule.

---

## Part 2 — Preparing a PR

Run `/security-review` on the pending changes, fix anything critical, then shape the PR per the conventions below.

### Embed the demo when creating the PR

**Gate — no exceptions.** A user-visible change needs demo media in the initial PR body. Create it with `demo-capture`; use an inline GIF or still images in the template's Demo section. Linked video files do not render inline. A non-visual change writes `N/A` with the reason. Never add the demo after opening the PR.

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
- [ ] **Demo embedded in the body** for any user-visible change (`demo-capture`), or `N/A` with a reason. Do this *before* `gh pr create`.
- [ ] `make check` (the project gate) is green. Name the result in **Verification**.
- [ ] PR body has **What / Why / Verification**; Verification names real checks (no banned vocab).
- [ ] Issue trailer is correct (`Closes` vs `Part of` — see above).
- [ ] `Co-Authored-By: Claude` trailer present on the commit(s).
- [ ] No secrets / proxy-pinned lockfiles / out-of-scope files in the diff.
- [ ] Repo-specific review dimensions (Part 1) walked for anything they apply to.
- [ ] Branch targets the integration branch (`production`), not a release/publish branch.

### Merge autonomy boundary
This restates the root `AGENTS.md` merge-autonomy default (#1878); that is the canonical statement. Routine feature PRs to `production` are delivered autonomously — push, open, squash-merge, clean up — **no confirmation needed**. **Confirm first only** when opening or merging a PR to `published/<target>` (the public-release approval boundary), it's a `--force`-push to a shared branch, or the working tree mixes unrelated concerns. When a build runs under an orchestrator that serializes sibling merges, **open the PR and stop** — let the orchestrator drive the merge and resolve any `plugin.json` version-line conflicts; do not rebase against sibling PRs.

---

## Quick reference

```
Reviewing?   /code-review (mechanics) → walk review-dimensions.md (6 repo-specific dimensions)
Security?    /security-review (mechanics) → check marketplace invariants
Preparing?   demo-capture FIRST (visible change) · What/Why/Verification body · name real checks · Co-Authored-By · Closes vs Part-of
Mergeable?   demo embedded at creation · make check green · body shape · issue trailer · no secrets · base = production
```
