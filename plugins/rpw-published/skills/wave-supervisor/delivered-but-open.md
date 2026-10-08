# Delivered-but-open issues — the pre-dispatch check and the close-out sweep

Companion to [SKILL.md](SKILL.md) steps 1 and 6 (#1846). **This file is the sole
owner of the commands and the decision table.** `SKILL.md`,
`dispatch-mechanics.md`, `merge-and-closeout.md`, `planning-defaults.md` and
`wave-state-template.md` each carry a one-line gist at the step where the check
matters — that is a pointer doing its job on a decision surface — and none of them
copies a command, the table, or the reasoning the gist compresses.

## Why an open issue is not evidence of undone work

The wave convention is `Refs #<n>`, never `Closes` — worker PRs land in a
non-default branch, so they cannot auto-close anything, and the single wave PR's
`Closes` list is the only thing that does
([`merge-and-closeout.md`](merge-and-closeout.md)). That is correct: it keeps an
issue open until its work is on `production`.

The cost is that **every close-out that does not complete leaves its delivered
issues open, indistinguishable from undelivered ones.** Wave `2026-09-18-backlog`
(#1837) paid a **full worker dispatch** on #1202, delivered by PR #1203 five
weeks earlier; the brief it generated then also sent that worker to a file #1758
had deleted, so one stale-open issue produced a stale brief too.

A full scan of 196 open issues against 790 merged PR titles found three matches,
so the class is **real but small and bounded** — cheap to check, expensive to skip.

## Pre-dispatch: ask three questions, not one

Run all three per issue, from the supervisor worktree, **before** creating the
worktree. Each answers a different question and a clean answer on one says
nothing about the others.

```bash
n=<issue-number>

# 1. Claimed by another workspace? (#568 — attribution)
make build-honor-check ISSUE="$n"        # wave-mechanics.sh honor-check "$n" elsewhere

# 2. An OPEN PR delivering it right now? (#1775/#1796/#1797 — a live race)
gh pr list --state open   --search "$n" --json number,title,headRefName

# 3. A MERGED PR that already delivered it? (#1846 — a stale-open)
gh pr list --state merged --search "$n" --json number,title,mergedAt
```

Question 3 is the one this file exists for. **A hit on it is a prompt to read —
never an auto-skip, and never a verdict** — see the next section for why, and the
section after that for how to decide.

### The search matches the number anywhere in the PR — so most hits are noise

`--search "$n"` is GitHub full-text over the whole pull request, title *and*
body. Three consequences, all measured:

- **A wave PR matches every issue it ever mentioned.** On wave
  `2026-09-23-backlog`, three of five cohort issues — #1850, #1853 and #1846
  itself — returned a merged-PR hit, and all three hits were wave PR #1872
  *filing them in its "Filed for later" list*. A merged PR that merely mentions
  an issue number is **the common case, not the exception.**
- **A bare number also matches unrelated prose.** `--search "847"` returns nine
  merged PRs; exactly one (#923) delivered #847.
- **`in:title` narrows hard but can miss the deliverer entirely.** For #847,
  `--search "847 in:title"` isolates the one real PR. For #1202 it returns only
  #1844 — the *follow-up* — because the actual deliverer #1203 is titled
  `feat(menubar): click a web-UI service row to open its *.localhost URL` and
  names the issue nowhere in its title. So run the wide search and read it; use
  `in:title` to sort the pile, never to replace it.

### Deciding: never auto-skip, and #847 is why

| What question 3 returns | What it means | Do |
|---|---|---|
| `[]` | nothing merged names it | dispatch |
| a PR mentioning `#n` in a list of *other* work — a wave PR's "Filed for later", a sibling's `Refs` | **not delivery** | dispatch |
| a PR whose diff covers the issue's acceptance | **delivered** | verify against the tree at `HEAD`, then close with the PR link as evidence — do not dispatch |
| a PR covering *part* of a multi-outcome issue | **partially delivered** | dispatch the remainder, and name the delivered part in the brief so the worker does not re-do it |

**An auto-skip on a merged-PR hit silently drops real work.** #847 matches PR
#923 (`versioning: … (#847)`) and is *legitimately* still open: it is a
multi-outcome issue whose outcome 3 is tracked separately as #936. Skipping it
would have dropped that outcome with no record.

"Verify against the tree" means **read the merged diff and then check `HEAD` for
the issue's acceptance**, not read the PR title and believe it. #1202's worker
did exactly that and correctly redirected to real work (PR #1844); the title
alone would have said "done".

Record the verdict where the next reader will find it: a one-line
`WAVE-STATE.md` event for a dispatch, or a closing comment naming the delivering
PR for a skip.

## Close-out: sweep for what the `Closes` list missed

The pre-dispatch check is the symptom guard. **The root cause is an incomplete
close-out**, and this sweep is what makes it visible to the *next wave* instead
of to the *next dispatch*.

The precise question is not "which issues does the wave PR mention" — a wave PR
body mentions dozens and most are correctly open. It is: **which issues did a
worker PR `Refs`, that the wave PR's `Closes` list then omitted?**

```bash
WAVE_PR=<the wave PR number>

BASE=$(gh pr view "$WAVE_PR" --json headRefName -q .headRefName)
# FAIL CLOSED: an empty BASE makes `--base ""` match every merged PR in the repo
# and the sweep reports the whole backlog as a finding.
[ -n "$BASE" ] || { echo "no wave branch for PR #$WAVE_PR — sweep NOT run"; exit 2; }

# `sort -u`, NEVER `sort -un`: `comm` compares lexicographically, so a numerically
# sorted input makes it emit issues that ARE in the `Closes` list. It trips on any
# wave mixing 3- and 4-digit issues — delivered=[847 1202] against closed=[1202]
# reported BOTH 847 and 1202 (#1846).
delivered=$(gh pr list --state merged --base "$BASE" --limit 100 --json body -q '.[].body' \
  | grep -oiE 'refs[[:space:]]+#[0-9]+' | grep -oE '[0-9]+' | sort -u)
closed=$(gh pr view "$WAVE_PR" --json body -q .body \
  | grep -oiE 'closes[[:space:]]+#[0-9]+' | grep -oE '[0-9]+' | sort -u)

comm -23 <(echo "$delivered") <(echo "$closed") | while read -r n; do
  [ -n "$n" ] || continue
  echo "  #$n delivered into $BASE but NOT in PR #$WAVE_PR's Closes list — state=$(gh issue view "$n" --json state -q .state)"
done
```

Run it **twice, and the first run is the one that pays**:

1. **With the wave PR open and NOT yet merged** (`merge-and-closeout.md` step 5,
   after the body is drafted). A hit here is one `gh pr edit --body` away from
   fixed — add the issue to the `Closes` list and GitHub auto-closes it on merge.
2. **Again after the merge, before the wave issue is closed** — a backstop for
   late fold-ins and for a skipped first run. A hit here costs a hand-close with
   the delivering worker PR linked, because there is no open PR left to edit.

Any hit is a finding, not a note. Running it only after the merge is what makes
the cheap remediation unreachable, so the post-merge run is the backstop and never
the only run.

It works. Against wave PR #1872 it names #1827 and #1829 — both delivered by
worker PRs, both absent from that PR's `Closes` list. Both were closed by hand
afterwards, so the damage was contained; had nobody noticed, they would have read
as eligible work in the next wave, exactly as #1202 did.

Three properties worth knowing before you trust a clean run:

- **The sort order is load-bearing and was wrong on first ship.** That live check
  passed only because every issue in it was 4-digit; with `sort -un` a mixed-width
  wave over-reported closed issues as findings. `tests/test_wave_delivered_but_open.py`
  extracts the two `sort` calls from this file and runs the `comm` pipeline over a
  deliberately mixed-width set, so re-adding `-n` fails the gate.
- **`Closes`-listed issues that are still open are a different, rarer failure.**
  GitHub honors the `Closes` list on merge to the default branch, so a sweep over
  the last five wave PRs for that shape returns nothing. Omission from the list
  is the failure mode; a failed auto-close is not.
- **The sweep reads PR *bodies*, so a worker PR that put `Refs #<n>` only in its
  commit messages is invisible to it.** That is a gap in the sweep, not proof the
  issue was undelivered — the pre-dispatch check above is the backstop.
