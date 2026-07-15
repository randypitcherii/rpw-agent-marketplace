---
name: changelog-release-notes
description: Use when drafting release notes or a changelog for this marketplace — "draft the release notes", "what changed since the last release", "write the changelog", "generate the release-log entry". Mines squash-merged PR titles/bodies + linked issues between the last v-tag and HEAD and renders the docs/release-log.md entry plus a PR/release description, shaped to this repo's calendar-first release flow (ADR-001).
---

# Changelog + Release Notes Generation

Draft the human-readable delta for a marketplace release. This repo's release
automation (`scripts/bump_marketplace_versions.py`) writes a release-log entry
with a **generic placeholder** summary — `"Automated production merge version
bump."` — and never mines PR titles or linked issues. This skill fills that gap:
it produces the real "what changed for the user" delta that an operator pastes
into the release log and the publish PR on the mirror.

## When to use

Trigger on: "draft the release notes", "what changed since the last release",
"write the changelog", "generate the release-log entry", "summarize this
release". Also use it as the drafting step before tagging a release
(`make tag-release`) and opening the publish PR (`make publish-public`).

## The tool

```bash
make release-notes                          # both drafts, auto base (latest v-tag or fallback)
make release-notes RELEASE_NOTES_BASE=<ref> # scope the delta from an explicit base
make release-notes RELEASE_NOTES_FORMAT=release-log   # just the release-log entry
make release-notes RELEASE_NOTES_FORMAT=pr-body       # just the PR/release body
```

Or call the script directly for finer control:

```bash
uv run python scripts/release_notes.py --base v2026.06.1202 --version 2026.06.1203
uv run python scripts/release_notes.py --base production~10 --no-gh   # offline
```

It is a **drafting tool**: it prints to stdout and never rewrites tracked files,
so it composes with the release automation instead of competing with it.

## How it's shaped to this repo

- **Base ref** defaults to the latest `v<marketplace-version>` tag (created by
  `make tag-release`, which tags `v$(metadata.version)` on `production`). **No
  `v*` tags exist yet** — until one does, the tool falls back to the repo root and
  prints a note telling you to pass `--base <ref>` (e.g. the last release
  commit) to scope the delta correctly. Always pass `--base` for a real draft.
- **Calendar-first versioning (ADR-001):** the version label defaults to today's
  `YYYY.MM.DD01`; pass `--version`/`RELEASE_NOTES_VERSION` to match the bump the
  release will actually allocate.
- **Conventional-commit prefixes:** squash subjects like `feat(runtime): …`,
  `fix(gdocs): …` are parsed into type + scope. Type drives the PR-body section
  (Features / Fixes / …); scope drives the release-log Scope field.
- **Trailing PR number** (`… (#269)`) is extracted as the PR reference; the PR's
  own number is excluded from the issue refs.
- **Issue references** (`#NN` in subject and body) are preserved as `refs #…`.
  They are labeled "refs", not "closes" — bodies cite epics and context issues,
  not only closed ones, so the tool does not over-assert closure.

## Two output formats

1. **`docs/release-log.md` entry** — the exact canonical template
   (`Type` / `Scope` / `PR` / `Summary` / `Checks`, plus `Highlights`). Replace
   the automated placeholder summary with this one. The release-log file
   prepends newest-first under the `## Releases` header.
2. **PR / release description body** — grouped by change type with scope tags
   and preserved PR/issue refs. Paste into the publish PR opened on the mirror
   by `make publish-public` (or the GitHub release notes).

## Workflow

1. Determine the base: latest `v*` tag, or the last release commit on
   `production` if no tag exists yet.
2. `make release-notes RELEASE_NOTES_BASE=<base> RELEASE_NOTES_VERSION=<next>`.
3. Review the draft — tighten the one-line summary to genuine user impact, drop
   noise. The tool drafts; you have final say on wording.
4. Paste the release-log entry into `docs/release-log.md` (newest at top, under
   `## Releases`) and the PR body into the publish PR on the mirror.

## Composition

- Drives the human-readable delta that the automated version bump would
  otherwise leave as a placeholder.
- Feeds the single-branch release flow (ADR-2026-05-19, amended by #314): tag
  the release on `production` with `make tag-release`, then open the reviewable
  mirror PR with `make publish-public`.
- Pairs with `versioning-standards` (version identity) and the release Makefile
  targets (`tag-release`, `publish-public`).
