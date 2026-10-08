# skill-recommender — reference

Templates and a worked example for [SKILL.md](SKILL.md). The filing mechanics (labels, title convention, per-type skeletons) come from the `marketplace-feedback` skill's reference — this file carries only the recommendation-specific shapes.

## Recommendation shape (fixed — every recommendation, verbatim headings)

```markdown
### <proposed-skill-name> — <new skill | improvement to `<existing-skill>`>

**Trigger evidence** — Cited occurrences, one per line:
- PR #N / issue #N / docs/<path> / transcript <date> / ecosystem: <source>
(Activity recommendations need ≥2 independent occurrences; ecosystem-only
recommendations name the source AND the local activity that would exercise it.)

**Proposed frontmatter** —
name: <kebab-case, unique across plugins — flat ~/.agents/skills namespace>
description: <house style, under 500 chars: "Use when …", 3+ concrete quoted
trigger phrases, and a "NOT for …" exclusion clause>

**Portability class** — portable | personal (per ADR-2026-06-12), with one line
of reasoning. personal ⇒ must live in plugins/rpw-private/; default to
personal on doubt.

**Ready-to-file issue body** — the marketplace-feedback feature skeleton,
filled in (Summary / Desired shape / Why / Sketch / Acceptance / Related).
For improvements: Related cites the existing skill's plugin path and the
Summary scopes the delta only.
```

## Evidence sources and degradation notes

| Source | Availability check | If unavailable |
|---|---|---|
| `gh pr list` / `gh issue list` | `gh auth status` | Skip; note "no gh access — activity scan limited to local docs" |
| `docs/`, ADRs, retros | Always (repo-local) | — |
| Session transcripts | Harness-dependent (e.g. `~/.claude/projects/*/` for Claude Code; other harnesses vary) | Skip; note "no transcript access in this harness" |
| Auto-memory / learnings logs | Harness-dependent (`MEMORY.md`, `.learnings/`) | Skip silently if absent — not all setups keep one |
| skills.sh leaderboard | Network fetch of skills.sh | Skip; note "skills.sh unreachable" |
| anthropics/skills | `gh repo view anthropics/skills` or web fetch | Skip; note it |
| `gh skill search` | `gh` ≥ 2.90.0 (`gh skill --help`) | Fall back to `gh search repos "agent skills" --sort stars` |

The final report always ends with a **Sources used / sources skipped** block. Recommendations from a thin evidence base (e.g. no transcripts, no network) are still valid but say so — the user weights accordingly at the checkpoint.

## Checkpoint table format

```
| # | Name | New/Improve | Evidence | Class | One-line rationale |
|---|------|-------------|----------|-------|--------------------|
| 1 | pr-conflict-triage | new | 3 PRs, 1 issue | portable | Merge-conflict recovery re-derived in 3 wave merges |
| 2 | doc-styling | improve | 2 issues | portable | Table-render gotchas re-explained; add to existing skill |
```

Then ask explicitly: file as-is / edit / drop, per row. Only after approval do any `gh issue create` commands run (via the marketplace-feedback flow).

## Worked example (condensed)

Run over this repo, July 2026:

- **Inventory**: 30 published + private skills; `~/.agents/skills` all repo symlinks (no local-only candidates).
- **Activity scan**: `gh` available; transcripts unavailable (non-Claude harness) — noted as skipped. PR bodies showed merge-queue conflict recovery narrated in three separate wave-merge PRs; issues showed two separate filings about MCP env-file relocation.
- **Ecosystem scan**: skills.sh reachable — top category "changelog/release automation" already covered locally (`changelog-release-notes`); anthropics/skills showed a richer progressive-disclosure shape for long skills → improvement candidate for one oversized local skill.
- **Output**: 3 recommendations (1 new portable skill with 4 cited occurrences, 2 improvements citing their skills), each with frontmatter draft + feature-skeleton issue body.
- **Checkpoint**: table presented; user dropped one improvement (already planned in an open issue the scan surfaced — dedupe win), approved two.
- **Filed**: two issues via the marketplace-feedback flow (`type: feature`, `priority: P2`), URLs reported; offered as candidates for the next wave.
