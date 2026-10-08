---
name: versioning-standards
description: Use when setting up versioning for a project, deciding when a version should bump, wiring a version/release gate into CI or a merge gate, comparing versions across components, or implementing version checks. Also covers exemption — the standard is firm, every surface is in scope, and only a human can approve an exception. Enforces the house calendar-first `YYYY.MM.DDNN` scheme, the per-PR bump rule (every merge to the integration branch is a release), and git-hash build identity.
---

# Versioning Standard

Three separable concerns. Get them right independently:

1. **What the version says** — calendar-first `YYYY.MM.DDNN`, derived from the release date.
2. **When it bumps** — in the PR that adds the release notes. Every merge is a release.
3. **What identifies a build** — the git short hash, not the version.

**Before all three, one rule: every version surface is in scope.** There is no category exemption —
not for a component deployed straight from a checkout, not for one that publishes no installable
artifact. A manifest still carrying a scaffold placeholder (`0.1.0`, `0.0.0`) is **non-conforming**,
and only a human can approve an exception. See §6.

## 1. The version string: calendar-first `YYYY.MM.DDNN`

```
YYYY.MM.DDNN
│    │  │ └── NN — zero-padded 2-digit intra-day sequence, starting at 01
│    │  └──── DD — zero-padded day of the release date
│    └─────── MM — zero-padded month of the release date
└──────────── YYYY — 4-digit year of the release date
```

The last dotted segment is **4 digits** (`DD` + `NN`): `2026.07.1201` is the first release
cut on 2026-07-12, `2026.07.1202` the second that same day, `2026.07.1301` the first the
next day.

- **No major/minor/patch decision exists** — the version is derived from the date. Never ask
  "is this a minor or a patch?"; the question has no answer here.
- **Every field is fixed-width and zero-padded**, so lexical order equals mint order. No
  custom comparison function is needed.
- Canonical decision: **ADR-001: Calendar-first versioning** in `rpw-agent-marketplace`
  (`docs/decisions/ADR-001-calendar-first-versioning.md`).
- **Don't introduce semver into new projects.** Migrating an existing one is a one-way bump
  to today's calendar version.

### One version source per component

| Kind | Source of truth |
| ---- | --------------- |
| JavaScript / TypeScript | `package.json` `version` |
| Python | `pyproject.toml` `[project].version` |
| Claude Code plugin marketplace | `.claude-plugin/marketplace.json` — the bumper syncs the identical version into each `plugins/*/.claude-plugin/plugin.json`, which the plugin loader requires; drift is a validation failure |
| Anything else | a single `VERSION` file at the project root |

Derived copies (dev manifests, command subtitles, embedded constants) must be **rewritten by
the bump script**, never hand-edited — otherwise they drift silently.

## 2. When to bump: every merge is a release

**Any PR that adds user-facing release notes must also carry the version bump in that same
PR.** There is no separate "Release v…" PR, and no queue of merged-but-unreleased work.

Why it holds:

- **A release queue goes stale.** Deferring the bump to a later release PR is how
  One extension shipped three waves of work while `package.json` still said
  `1.15.0` — anyone asking "which version am I running?" got a wrong answer.
- **It matches reality.** Local/prod installs build straight from the integration branch, so
  the merge *is* the release whether or not a version records it.
- **Docs-only PRs add no notes, so they bump nothing** — the rule never mints empty releases.
- **Multiple merges a day** are absorbed by the intra-day `NN` sequence.
- **Parallel branches that both bump** conflict on the version file. That's the design:
  whoever rebases second re-runs the bump and re-derives from the date. (Waves serialize
  merges through a wave branch, so the supervisor handles this mechanically.)

## 3. Enforce it — pick the shape that fits the repo

The rule only holds if something fails when it's broken. Two shipped shapes:

### A. CI auto-bump (repo has GitHub Actions)

A workflow bumps the version automatically. **Bump post-merge, on push to the integration
branch — not on the PR branch.** The PR-branch shape pushes the bump asynchronously to the
PR head; a fast `merge --squash --delete-branch` wins that race, shipping the merge
unbumped (fired three times in two days — see the reference repo's #480). Post-merge, the
bump follows the merge: no race by construction.

A workflow pushing to its own trigger branch needs layered recursion guards: default
`GITHUB_TOKEN` pushes don't retrigger `push` workflows (primary); a job `if:` on the bump
commit's message marker; and the idempotency gate below (load-bearing — the bump commit
touches the version files themselves).

The locally testable idempotency rule:

> **Skip** the bump when the head (the merge commit) carries a version **strictly ahead**
> of the base (its parent). Equal, behind, or unparseable ⇒ **bump** (fail open: the
> bumper normalizes the manifest wholesale, so running it is safe).

Delegate version ordering to the bumper's parse function so gate and bumper agree on
"ahead". Serialize back-to-back merges with a `concurrency` group; anchor each run's
diff range on its own merge SHA, minting from the tip.

Reference: `rpw-agent-marketplace` — `.github/workflows/push-to-production__auto-bump.yml`,
Examples: an `autobump_gate.py` with a pure, unit-tested `decide()` helper, plus the repository's version-bump script.

### B. Local merge gate (repo has no CI)

Fail the repo's merge gate — the command that defines "green", e.g. `make check` — unless the
bump ran, with a failure message naming the exact command to run. Contract and reference:
`references/enforcement-and-bookkeeping.md`.

## 4. Release bookkeeping: roll or append

Either roll a `CHANGELOG.md` `[Unreleased]` section into a dated heading, or append one entry per
merge to `docs/release-log.md`. Pick one per repo; **automation owns the dated archive, curated
highlights live in the PR body.** Both shapes: `references/enforcement-and-bookkeeping.md`.

## 5. Git-hash build identity

The version is for humans. **The git short hash is what actually identifies a build** — use
it, not the version, for any drift/sync check between components.

Display format: `v{version} · {hash} · {date}` — e.g. `v2026.07.1502 · 56650a6 · 2026-07-15`.

### Rules

1. **Resolve git info at startup**, cache for the process lifetime.
   - `git rev-parse --short HEAD` → hash; `git log -1 --format=%as` → date (YYYY-MM-DD).
   - Always wrap in try/catch — **git is absent from production builds** (store installs ship
     without `.git`). Where the build is detached from the repo, bake the hash in at build
     time instead of resolving at runtime.
2. **No shell injection.** Python: `subprocess.run(['git', ...])`, never `os.popen()` or
   `shell=True`. TypeScript: `execFileSync('git', [...])`, never `execSync('git ...')`.
   Always set a 1–3s timeout.
3. **Compare hashes, never versions**, for multi-component drift detection.
   - Expose hash + date in health/status endpoints.
   - Treat unknown/empty hash as **compatible** (graceful degradation for non-git builds).
   - Never hardcode a fallback that looks like a real version — use `"unknown"`, never `"0.1.0"`.
4. **Health endpoint schema** (for services):
   ```json
   {
     "version": "2026.07.1502",
     "git_hash": "56650a6",
     "git_commit_date": "2026-07-15"
   }
   ```

Reference implementations (Python server, TypeScript client, and the hash-comparison helper):
`references/git-hash-identity.md`.

## 6. The standard is firm. Exceptions need a human.

**Every version surface in the repo is in scope** — published packages, plugins, MCP servers,
shared libs, and apps deployed straight from a checkout. A manifest still carrying a scaffold
placeholder (`0.1.0`, `0.0.0`) is **non-conforming, not exempt**; fix it by putting it under the
bumper, never by hand-stamping a version that then freezes.

**No agent may grant an exemption** — not to itself, not to the component it is working on, however
good the argument reads. **An exception is valid only when a human explicitly approves it**, and
the approval is recorded in its own ADR. Proposing one is welcome: raise an issue, name the surface
and the reason, and wait for the answer.

Two arguments that look convincing and are not:

- *"A calendar day is coarser than our redeploy rate."* The scheme is `YYYY.MM.DD`**`NN`** — the
  trailing counter is same-day granularity. This objection describes a scheme nobody uses.
- *"Nothing resolves this component by version, so the number is unread."* Version identity is for
  humans reading a running system (§1); "no external consumer" is an argument for *why* it is cheap
  to bump, not for skipping it.

**Git-hash identity (§5) is complementary, never a substitute.** A component reports both.

Worked example of getting this wrong: `rpw-agent-marketplace`'s
`docs/decisions/ADR-2026-08-07-app-version-identity.md` — a worker-authored exemption, **rejected**,
retained as the record of why the human-approval rule exists.

## Setting this up in a new project

1. Read §6 first: every version surface is in scope, and only a human can approve an exception.
   Don't open by deciding this component is the special case.
2. Pick the version source from the table in §1; set it to today's `YYYY.MM.DDNN`.
3. Write a bump script that derives the version from **today's local date** (`NN = 01`, or
   increment if a release already exists for today) and rewrites every derived copy in
   lockstep. Give it a `DRY_RUN` mode that prints the plan and writes nothing.
4. Pick a bookkeeping shape from §4 and have the bump script own it.
5. Wire the enforcement from §3 — CI auto-bump if the repo has Actions, otherwise a step in
   the merge gate.
6. Keep the gate's decision logic in a **pure, unit-tested function** separate from its CLI
   wrapper. Both reference implementations do this; it's what makes the rule testable
   without a live PR.
7. Document the scheme and the per-PR rule in the repo's own `docs/versioning.md` + agent
   instructions, so agents follow it without loading this skill.
