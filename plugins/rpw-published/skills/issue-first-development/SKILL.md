---
name: issue-first-development
description: The gate that runs before building anything in a version-controlled repository — a tracking issue must exist first, found or filed. Load at the START of any request to build, implement, add, fix, refactor, or wire up something in a git repo, before writing code. Forks on repo class — private-and-mine takes house standards, public applies a minimum-necessary disclosure filter, someone else's repo respects their conventions too. Authoring the issue itself is delegated to `issue-creation`.
---

# Issue-first development

Two failures come from starting to code in a tracked repo with no issue behind it.

1. **Invisible work.** No statement of the problem before the solution, nothing for a PR to link, nothing a future session or a different harness can reconstruct intent from. The commit says *what*; only the issue says *why*, and by then the reasoning is gone.
2. **Uncontrolled disclosure.** On a **public** repo the issue publishes your reasoning — internal hostnames, customer names, unreleased plans, workspace URLs — often weeks before any code lands. The issue is the leakiest artifact in the workflow and the one written with the least care.

**The rule: no build in a version-controlled repo without an issue.** Find one or file one, before code. Not after, not "if it turns out to be big".

This skill owns the **gate** and the **disclosure fork**. `issue-creation` owns how the issue is written — do not restate its body shape, label rules, or ownership detection here.

## 1. Does the gate apply?

Applies when **both** hold: the work lands in a git repository, and it changes that repository (code, config, docs, tests, CI).

**Exempt** — proceed without an issue:

- Reading, searching, explaining, or reviewing. No change, no issue.
- A scratch directory or throwaway clone you will delete.
- Reproducing a bug to understand it — the *fix* needs an issue, the repro does not.
- A repo whose maintainers explicitly say not to file (some accept PRs directly; honor that).
- The user has an issue open and names it. That *is* the issue — link it and go.

**Not exempt, though it feels like it:** one-line fixes, typos in shipped docs, "I'll just quickly…". Size is not the test; whether the repo tracks its work is. If the change is genuinely too small to describe, describe it in one sentence and file it — that costs ten seconds and leaves the trail.

When the applicability itself is unclear, **ask** in one line rather than guessing in either direction.

## 2. Find before you file

Duplicate issues are worse than missing ones — they split discussion and hide the thread where the decision already got made.

```bash
gh issue list --state all --search "<3-5 distinctive keywords>" --limit 30
```

Search **all** states, twice, with different vocabulary: the user's words, then the codebase's words. Then:

| What you find | Do this |
|---|---|
| **Open, same problem** | Use it. Comment with the new context you have; do not file a sibling. |
| **Open, adjacent** | File a new issue that references it (`Refs #N`). Overlapping-but-different is a real issue, not a duplicate. |
| **Closed as fixed** | Verify the fix actually shipped in the current tree before refiling. Often it did and the ask is already satisfied. |
| **Closed as wontfix** | Do not refile without naming what changed. Raise it with the user instead. |
| **Nothing** | File it. |

## 3. Fork on repo class — this is the load-bearing step

Classify with `issue-creation`'s classifier rather than eyeballing the URL:

```bash
uv run --no-project python "$CLAUDE_PLUGIN_ROOT/skills/issue-creation/ownership.py" --repo owner/name
gh repo view --json visibility -q .visibility   # PUBLIC | PRIVATE | INTERNAL
```

Ownership and visibility are **independent axes**, and both change the handling:

| Repo class | Handling |
|---|---|
| **Private + mine** | House standards, nothing more. Write freely — internal hostnames, customer names, unreleased plans, and full reasoning all belong here. This is the default case and carries no extra ceremony. |
| **Public + mine** | Full house structure, run through the **disclosure filter** below. My conventions still govern shape and labels. |
| **Not mine** (any visibility) | Their standards win on shape, template, labels, and title convention; mine fill the gaps. Apply the disclosure filter regardless of the repo's visibility — someone else's private repo is still not my disclosure boundary to spend. |

`viewerPermission: WRITE` or `ADMIN` is **not** ownership. Maintaining someone else's project is exactly when their conventions govern. Unknown ownership resolves to *not mine*.

## 4. The disclosure filter (public, or not mine)

Two principles, applied in order:

1. **Nothing private.** Not "lightly paraphrased" — absent.
2. **Nothing beyond the minimum.** Of what remains disclosable, include only what a contributor needs to understand the problem and verify the fix. Extra context is not generosity; it is surface area.

🚫 **Never in a public or foreign issue:**

- Internal hostnames, internal proxy/registry URLs, workspace URLs, dashboard links
- Customer, account, or prospect names — and identifying combinations ("the regional insurer we lost in Q3")
- Colleague names beyond public GitHub handles already in the thread
- Unreleased roadmap, pricing, deal, or headcount detail
- Tokens, credentials, connection strings, config with secrets — even redacted-looking ones
- Raw logs and stack traces pasted whole (they carry paths, hostnames, and usernames). Quote the two relevant lines.

✅ **The translation move.** Do not delete the problem — restate it at a level that is true and shareable:

| Private framing | Public framing |
|---|---|
| "Our `<internal>-proxy` mirror returns 403 for mlflow" | "Installs against a mirrored package index fail for one dependency" |
| "Blocking the Northwind Freight POC on Friday" | "Blocks a time-sensitive evaluation" |
| "Broke during the migration off our internal fork" | "Broke when moving to the upstream release" |

The second column still supports a fix. If a claim *cannot* survive translation, that is a signal it belongs in a private issue that the public one references by number only.

**One more pass before filing:** reread the drafted body as a stranger, hunting only for what you would not want indexed by a search engine forever. Deleting an issue does not unpublish it.

## 5. Ask, do not guess

Stop and ask when:

- **Ownership or visibility is ambiguous** — a fork, a repo under an org you belong to but do not run, a vendored copy.
- **A load-bearing detail may not be disclosable.** The judgment about what is safe to say about the user's employer, customers, or unreleased work is theirs, not yours. Offer the translated version and let them approve it.
- **A near-duplicate is close but not identical** and reusing it would bury a distinct problem.
- **The repo's conventions conflict with the house standard** in a way that changes the issue materially — not for cosmetic differences, where theirs simply win.

One question, with the concrete options. Do not stall the whole build on a question you can answer by reading `CONTRIBUTING.md`.

## 6. File, then build

Hand off to `issue-creation` for the body, labels, and `gh issue create` invocation. Then, before any code:

1. **Report the issue number and URL** to the user.
2. **Reference it in commits and the PR** — `Refs #N` while work is in flight; the closing keyword only where the workflow expects it (in this monorepo's fenced worker flow, never — the supervisor closes issues at wave close-out).
3. Build.

If a build request produced code before an issue existed, that is the failure this skill prevents — file it now, reference it in the commit, and note the ordering slip once. Do not backfill silently.

## Related skills

- `issue-creation` — how to write the issue. This skill decides *whether and where*; that one decides *what it says*. One direction only: this composes onto it, never replaces it.
- `generate-backlog` — many issues at once from a broad ask; its user checkpoint is authoritative.
- `human-todo` — personal task tracking. If the ask is a personal reminder rather than repo work, the gate does not apply.
- `communication` — problem-before-solution ordering, which is exactly why an issue precedes code.
