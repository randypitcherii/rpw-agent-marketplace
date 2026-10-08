---
name: staleness-sweep
description: Scheduled staleness and debt sweep over the skill library, docs, and AGENTS files — run the read-only scanner, verify each finding against the tree, and land ONE rollup issue of proposed fixes for a human to approve. Trigger on "run the staleness sweep", "sweep the skills for drift", "are our docs still true", "check for stale skills", or as the weekly maintenance automation. NOT for defects in merged code (use periodic-review) and NOT a fixer — it never edits a skill or a doc.
---

# Staleness sweep — diagnose drift, propose, let a human approve

Skill and doc drift is invisible to per-PR review. Nothing in the diff is wrong; the world moved underneath the words. the retired `superset-launch` sat grounded against a CLI that had left PATH (#739), the wave-kickoff migration to omnigent (#795) left sibling dispatch skills pointing at the old substrate, and #1025 / #1040 / #1026 were all found by somebody tripping over them. This sweep converts that into a steady drip of small reviewable proposals.

The sibling skill is `periodic-review`: same operating model (findings become issues, never commits), different failure class. That one reads the merged code delta for defects. This one reads authored guidance for **disagreement with reality**.

## The boundary — read this before anything else

**Diagnose, propose, stop.** A sweep that edits a skill is a failed sweep, however obvious the fix looked.

- You do not edit a skill, a doc, or an AGENTS file. Not one character, not "while I was there".
- You do not commit, do not push, do not open a pull request, do not dispatch a worker to do it for you.
- Your entire output is **one issue** and a short report. A human approves each proposal from there.
- The scanner cannot break this rule even if instructed to: it opens no file for writing and performs no git or GitHub write. `--self-check` fails the moment a mutation verb appears in the sweep surface. Your half of the boundary is the half that is only enforced by you.

## Step 1 — run the scanner

```bash
automation/bin/staleness-sweep.py --format text          # read it yourself
automation/bin/staleness-sweep.py > /tmp/sweep.json      # machine-readable
```

It is read-only, takes about two seconds, and needs no credentials. Every finding carries `lens`, `severity`, `file`, `line`, `evidence`, and a `proposal` **sketch**. The sketch is a starting point, not the fix.

Scope notes that will otherwise waste your time: point-in-time records — ADRs, plans, release notes, research — are outside the corpus on purpose, because an ADR describing the world of six months ago is not stale. `--lens <name>` narrows a run; `--no-probe` skips the `tool --version` subprocesses.

## Step 1b — add the usage snapshot (#1959, #1960)

The scanner reads what the guidance *says*. This reads whether anyone *uses* it, and
whether it *helped*:

```bash
make usage-report          # writes the week's usage.snapshot rows, prints `rollup: <path>`
```

The `rollup:` path holds a ready-to-paste `## Usage` section with two halves that you
treat differently:

- **Four decay rules** (`decay`, `dead`, `bloat`, `churn>use`) — proposals, verified and
  refutable exactly like a scanner finding. A hit you cannot explain is **refuted**, not a
  deletion.
- **An `### Outcome signals` table** (#1960) — **evidence, not findings.** Friction per
  skill plus how the sessions that used it ended. Carry it into the rollup as printed;
  never refute a row and never turn one into a proposal.

Thresholds, the reason the outcome columns exist at all, and the two coverage limits worth
restating in the issue: [references/usage-snapshot.md](references/usage-snapshot.md). Read
it before you report a usage hit.

## Step 2 — verify every finding against the tree

The scanner is deliberately mechanical, so some findings are wrong. **Refute before you report** — the same discipline `periodic-review` uses, and the reason a sweep is trusted rather than skimmed.

| Lens | Proven mechanically | Your judgement call |
|---|---|---|
| `dead-reference` | the path is absent from the tree | is the mention illustrative, or a real broken pointer? if the scanner found the file's new home, is that the same file? |
| `grounding-drift` | the CLI is not on this PATH | is the tool genuinely retired, or just uninstalled on this machine? a pinned version may be deliberate |
| `cross-reference` | the link, anchor, or skill name does not resolve | which side is wrong — the reference, or the thing it points at? |
| `substrate-lag` | one place calls a name retired while another does not | is the retirement claim itself correct? |

Open each cited file at the cited line. For anything non-obvious, spawn a `general-purpose` agent to argue the finding **cannot** be real and default to refuted on a tie. Record how many findings you dropped — that number is how a reader calibrates the rest.

## Step 3 — dedupe, then land one issue

Search the open backlog before filing (`gh issue list --search`), and fold anything already tracked into a one-line reference instead of a duplicate.

File **one rollup issue** per run, per `issue-creation` and `communication`:

- Title: `staleness sweep <date> — <N> verified findings`.
- Body: findings grouped by lens, ranked by severity, each with `file:line`, the evidence, and **an exact proposed edit** — the current wording and the replacement, not a description of a change. That precision is what makes a human able to approve in one read.
- Then the `## Usage` section from Step 1b's `rollup:` file — rule hits verified the same way, the `### Outcome signals` table pasted as printed. One issue, all of it; a second usage-only issue defeats the point of a rollup.
- A short "refuted" section: what the scanner reported and you dismissed, with the reason. This is what stops the sweep from decaying into noise.
- Labels: `type: task` plus severity-appropriate priority. Never `status: in-progress` by hand.

If a single finding is severe and self-contained, say so and recommend a dispatch — but that dispatch is a separate, deliberate decision, not part of this run.

## Step 4 — report and stop

Report the tally: findings by lens, how many survived verification, how many were already tracked, the issue number. Then stop. Do not begin fixing what you just proposed, even if the human is likely to say yes.

## Cadence

Weekly is the starting point. The definition lives in `docs/process/staleness-sweep.md`; that runbook also records why the cadence hook is documented rather than wired, and what the automation-definition mechanism will need from it. Read it before changing when or where the sweep runs, and treat `automation-standards` as binding once it is scheduled: the recorded report is the run's health, not its exit code.

## Why the proposals stay proposals

A reviewer that also fixes inherits the builder's incentives — the reason `periodic-review` files issues instead of pushing commits. Guidance is worse: a wrong "fix" to a skill silently changes how every future agent behaves, and the next reader has no way to tell that a machine decided it. So the sweep buys accuracy with human approval on every edit, and the cost of that is one issue a week.
