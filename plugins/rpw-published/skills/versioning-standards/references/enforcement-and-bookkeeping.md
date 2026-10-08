# Enforcement shape B + release bookkeeping

Companion to `SKILL.md` §3–§4. Shape A (CI auto-bump) stays inline in the skill; the no-CI
shape and the two bookkeeping shapes live here.

## B. Local merge gate (repo has no CI)

Fail the repo's merge gate — the command that defines "green", e.g. `make check` — unless
the bump ran. The agent is then forced to bump before it can merge.

Gate contract for a `CHANGELOG.md` + `[Unreleased]` repo — all three must hold:

1. the `## [Unreleased]` placeholder **exists** (structure guard),
2. its body is **empty** — pending notes mean the bump that rolls them never ran,
3. the version source **equals the newest dated changelog heading**, so the shipped version
   string and the changelog archive can't drift.

Make the failure message name the exact command to run (`Run \`make version-bump\``). The
gate is read by agents; a diagnostic without a remedy costs a round-trip.

Shape the implementation as a **pure predicate plus a thin CLI wrapper**, so the decision is
unit-testable without a live merge:

```
checkVersionRolled({ changelog, version }) -> { ok: boolean, reason?: string }
```

The wrapper reads the two files, calls the predicate, prints `reason` and exits non-zero on
failure. Keep every filesystem read in the wrapper and none in the predicate — that split is
what makes the gate testable from fixtures.

> **No live reference implementation ships in this repo.** The one this doc used to cite
> A legacy extension's separate version-check script was **deleted on import** into
> `rpw-agent-marketplace`: once the repo had CI, shape A took over and the local gate became
> redundant. That is the expected lifecycle — **shape B is for repos with no CI, and retiring it
> is the right move when CI arrives.** Do not reintroduce it alongside shape A.

## Release bookkeeping: roll or append

Two shapes, both fine — pick one per repo and let the tooling own it:

- **`CHANGELOG.md` with `[Unreleased]`** — the bump script rolls `## [Unreleased]` into
  `## [<version>] - <YYYY-MM-DD>` and inserts a fresh empty `## [Unreleased]` above it. The
  roll must be a **no-op when `[Unreleased]` is empty or absent** and **idempotent** — never
  create a dated heading twice for the same version. Run the roll *inside* the bump script, so
  one command moves the version and the archive together.
- **`docs/release-log.md`, one appended entry per merge**, newest at top, drafted from
  merged PR/issue history. (`rpw-agent-marketplace`: `make release-notes`, and the
  `changelog-release-notes` skill.)

Either way: **automation owns the dated archive; curated highlights live in the PR body.**
