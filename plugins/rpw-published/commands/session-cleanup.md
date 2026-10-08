---
name: session-cleanup
description: End-of-session teardown — verify the current worktree has nothing uncommitted or unmerged, remove it, then close this omnigent session. Aborts loudly if anything would be lost.
allowed-tools: Bash, Read, mcp__omnigent__sys_session_get_info, mcp__omnigent__sys_session_close
user-invocable: true
---

# /session-cleanup — tear down this worktree session

Ordered pipeline for the end of a session whose work has already landed: prove
nothing gets lost, remove the worktree, then close your own omnigent session.
**Any failed check → report exactly what you found and stop. Report-only, no
remediation:** never commit, stash, delete, ship, or kill anything to clear a
blocker, and don't ask whether to — the user reads the report and issues the
next instruction (override, ship it, clean it) themselves. Never reach for
`--force` or `-D` to make a check pass; a refusal from git *is* a failed
safety check. The single exception is the squash-merge equivalence path in
check 4, which earns a scoped `-D` by proving the content landed.

## Phase 1 — verify nothing gets lost (all must pass)

1. **Linked worktree, not the main clone.** `git rev-parse --git-common-dir`
   must differ from `git rev-parse --git-dir` (equivalently: the cwd is a
   non-first entry in `git worktree list`). In the main clone → abort; there
   is nothing to tear down.
2. **Fresh remote state.** `git fetch origin` before any reachability check.
3. **Clean tree.** `git status --porcelain` is empty — no uncommitted changes,
   no untracked files. Anything present, including untracked scratch files,
   is a blocker: list what's there and stop. Don't judge files disposable on
   the user's behalf.
4. **Everything merged.** `git log origin/<default-branch>..HEAD --oneline` is
   empty — every local commit is reachable from the integration branch
   (usually `origin/production`). If the branch has an upstream, also confirm
   `git log @{u}..HEAD` is empty.

   **Squash-merge equivalence path (#1178).** This repo squash-merges every
   PR, so a properly-shipped branch's commits are *never* reachable from the
   integration branch — reachability alone fails every legitimate close-out.
   When the log is non-empty, the check still passes if BOTH proofs hold:

   1. **GitHub says merged.** `gh pr view <branch> --json state,mergeCommit`
      reports `state: MERGED`. GitHub's record, not git topology, is the
      source of truth for a squash merge. `OPEN`, `CLOSED`, or no PR found →
      hard stop, report as before.
   2. **Content landed.** Start by comparing every file the branch touched
      against the integration branch tip:

      ```bash
      base=$(git merge-base origin/<default-branch> HEAD)
      git diff --name-only "$base"..HEAD -z \
        | xargs -0 git diff --exit-code origin/<default-branch> HEAD --
      ```

      Exit 0 → equivalent, proof complete. A differing file is **not yet a
      blocker (#1189)**: the tip moves on after a merge, so this comparison
      alone cannot tell "the branch holds content that never landed" from
      "the integration branch edited the file afterward" — opposite
      situations. Settle it against the merge commit proof 1 already
      returned, which is the branch's content *as it actually landed*:

      ```bash
      git diff --quiet <mergeCommit> HEAD -- <file>   # exit 0 → landed
      ```

      | HEAD vs integration tip | HEAD vs merge commit | Verdict |
      |---|---|---|
      | identical | — | landed, untouched since ✅ |
      | differs | identical | landed; integration branch edited it later ✅ |
      | differs | differs | genuinely unlanded 🚫 |

      **Only the third outcome is a hard stop** — report those files and
      stop, as before. The second passes, and the close-out says which files
      have moved on ("6 files edited in `production` since the merge; all
      matched their as-merged state"), so the reader sees what was checked
      rather than a bare pass.

   Both proofs pass → record the PR number and merge commit for the
   close-out report; this also authorizes the `-D` in Phase 2 step 4.
   Anything less keeps the report-and-stop behavior.
5. **No surviving processes.** Deleting a worktree does not kill what runs in
   it (#644). Check for background tasks/monitors of this session still
   writing into the worktree, and best-effort sweep other processes rooted
   here (`pgrep -lf "$PWD"`, ignoring this session's own shell). Survivors →
   name them and stop; never kill them yourself.

## Phase 2 — remove the worktree

1. Resolve the main clone path (first entry of `git worktree list`) and note
   the current worktree path + branch.
2. `cd` to the main clone first — the shell must not keep its cwd inside a
   directory about to be deleted. Use absolute paths from here on.
3. `git worktree remove <worktree-path>` from the main clone — **no
   `--force`**. If git refuses, something in Phase 1 was missed: go back,
   don't override.
4. `git branch -d <branch>` — lowercase `-d` by default. A refusal means
   unmerged commits; investigate, never escalate to `-D` on your own
   judgment. **Exception:** when check 4 passed via the squash-merge
   equivalence path, `-d` is *guaranteed* to refuse (the squashed commit
   stays topologically unmerged forever) — use `git branch -D <branch>`
   directly and cite the PR number + merge commit from the proof in the
   close-out report. The proof, not the refusal, is what authorizes it.
5. `git remote prune origin` (best-effort tidy of merged remote branches).

## Phase 3 — close this omnigent session (last action)

1. Deliver the close-out report **before** the close call: what was verified,
   what was removed (worktree path, branch), anything left behind on purpose.
2. `sys_session_get_info` with no `session_id` → this session's
   `conversation_id`.
3. `sys_session_close` with that id, as the very last tool call. A terse
   sign-off after it is fine — assume nothing later renders.
4. If the omnigent tools are unavailable (not an omnigent-hosted session) or
   the close errors, say so and leave the session for manual close — never
   retry with anything process-killing.

## Scope — this command owns ONE worktree; the sweep owns the rest (#1231)

Everything above is about **the worktree you are in**. The other worktrees and
every orphaned local branch are explicitly **not yours to reason about here** —
this command has no visibility into whether their trees are dirty or their work
landed, and guessing is how real work gets deleted. Do not widen its scope, and
do not hand the user a manual `git worktree remove` / `git branch -D` list.

Point them at the repo-level sweep instead:

```bash
make branch-hygiene              # dry run: every dead branch/worktree + the evidence
make branch-hygiene APPLY=1      # reap only what is provably dead
```

It reaps on a squash-safe proof (upstream `[gone]` **and** exactly one MERGED PR
whose head matches the branch tip **and** a clean tree **and** no live process in
the worktree **and** no active claim) and refuses everything else with the reason
printed — the same standard as Phase 1 here, applied repo-wide. It re-proves each
row immediately before deleting it, so a commit that lands after the report was
printed aborts that deletion rather than losing the work. Mention the sweep in the
close-out report when you noticed stale siblings; never run `APPLY=1` yourself as
part of this command.

⚠️ **The sweep's process check is a lower bound, and this command is why that is
acceptable.** The sweep refuses when a live process's **argv** names the worktree
path — enough to catch a dev server or agent launched with a path in its command
line. It cannot see a process that no longer names the path: an interactive shell
merely `cd`-ed into the worktree, an inherited file descriptor, or a daemon that
chdir-ed and re-exec'd. Killing processes (#644) stays here, in the command that
runs *inside* the worktree it is about and can see its own background tasks. So
when you finish a session, do your own process cleanup here — do not leave it for
the sweep, which will either refuse (leaving the worktree behind) or, for a
process it cannot see, remove a checkout out from under something still running.

Anything after `/session-cleanup` is treated as context (e.g. "the PR just
merged"), not as permission to skip checks. There are no flags and no force
mode: if the tree isn't provably safe to delete, the command's whole output
is the blocker report — what exists, where, and why it blocks. The user
decides what happens next in a follow-up message; overrides, shipping the
work (`/ship-it`), or discarding files are theirs to order, never yours to
offer or perform.
