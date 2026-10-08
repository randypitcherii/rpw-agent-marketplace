---
name: skill-recommender
description: Use when deciding what skills the library is missing or which existing skills need improvement — evidence-driven gap analysis over recent activity (PRs, issues, docs, session artifacts) and the wider skill ecosystem. Trigger on "what skills are we missing", "recommend new skills", "skill gap analysis", "should this be a skill?", "audit the skill library". Ranked recommendations (evidence, name + description, portability class, issue body); files issues only on explicit confirmation.
---

# Skill Recommender

Turn evidence — what the agent keeps re-explaining, what the backlog keeps re-filing, what the ecosystem ships that this library lacks — into **ranked skill recommendations**: new skills and improvements to existing ones. This skill *recommends*; it never authors skills and it files issues only after an explicit user confirmation, via the `marketplace-feedback` skill's house shape.

Pipeline: inventory → activity scan → ecosystem scan → synthesize → **user checkpoint** → file (on approval) → hand off.

## When to invoke

Use when the question is about the *skill library itself*: "what skills are we missing?", "recommend new skills", "should this recurring thing be a skill?", "audit our skills against the ecosystem", or a periodic library review.

**Skip when**: filing one already-known issue (`marketplace-feedback` skill directly), analyzing plugin structure/test health (the `/plugin-feedback` command), or generating a product backlog for a repo (`generate-backlog` skill).

## 1. Inventory the local library

Build the dedupe baseline before scanning for gaps:

- **Canonical source**: every `plugins/*/skills/*/SKILL.md` in this repo — collect `name` + `description` frontmatter.
- **User-scoped extras**: `~/.agents/skills/` (the ADR-2026-06-12 fan-out location) — skills there that are *not* repo symlinks are locally-authored candidates the library may want to absorb.

A recommendation that substantially overlaps an existing skill's trigger surface must cite that skill and become an **improvement** recommendation (delta only) or be dropped.

## 2. Gap analysis vs activity

Look for the **"explained three times, no skill" signal**: the same procedure derived, explained, or debugged repeatedly with no skill covering it. Scan whatever session artifacts the current harness exposes, in this order, and degrade gracefully — use what is available, and record what was skipped:

| Source | How | Signal |
|---|---|---|
| Merged PRs | `gh pr list --state merged --limit 100 --json title,body,mergedAt` | Repeated manual procedures narrated in PR bodies; recurring fix categories |
| Issues (all states) | `gh issue list --state all --limit 200 --json number,title,state,labels` | Recurring friction reports; the same "how do I X" filed more than once; closed issues that re-litigate a known procedure |
| Repo docs/retros | `docs/` (retros, ADRs, process docs), README, AGENTS.md | Procedures documented in prose that agents must rediscover per session |
| Session transcripts / memory | Harness-dependent (local transcript dirs, auto-memory files) | Corrections and preferences repeated across sessions (`.learnings`-style logs) |
| Learned-skill rollup (optional) | When a local learned-skill layer writes a promotion rollup, read the newest one | Lessons already loaded repeatedly — each candidate is pre-counted evidence for a new skill or an improvement |

Session-transcript access varies by harness — never block on it. When a source is unavailable (no `gh` auth, no transcript access, no memory files), skip it and say so in the report: the evidence base must be explicit so the user can weight the recommendations.

An activity gap needs **≥2 independent occurrences** to become a recommendation; one-offs go in an "observed once — watch" appendix, not the ranked list.

## 3. Gap analysis vs ecosystem

Compare the local inventory against what the ecosystem actually ships. Network access varies — same graceful degradation: try each source, note what was unreachable.

- **skills.sh leaderboard** — install-count-ranked skills; high-install categories absent locally are high-value candidates.
- **anthropics/skills** — Anthropic's reference library; strong signal for *shape* improvements to existing local skills, not just new ones.
- **`gh` search** — `gh search repos "agent skills" --sort stars`, or `gh skill search <topic>` where the `gh` version supports it, for topic-specific coverage checks.

Filter ecosystem candidates through *this* library's actual usage: recommend a category only when local activity (step 2) or the user's stated workflows would exercise it. "Popular elsewhere" alone ranks low.

## 4. Output contract

Every recommendation — new skill or improvement — carries exactly:

1. **Trigger evidence** — the cited occurrences (PR numbers, issue numbers, doc paths, transcript dates) or ecosystem source. No evidence, no recommendation.
2. **Proposed name + `description:`** — kebab-case name unique across the repo (flat `~/.agents/skills` namespace); a house-style description with concrete trigger phrases and a NOT-for clause, under 500 chars.
3. **Portability class** — `portable` or `personal` per ADR-2026-06-12 (`docs/decisions/ADR-2026-06-12-skill-distribution.md`), which determines placement: `personal` must live in `rpw-private`; default to `personal` on doubt.
4. **Ready-to-file issue body** — the `marketplace-feedback` skill's feature skeleton, filled in. Improvements to existing skills cite the skill and scope the delta.

Templates and a worked example: [reference.md](reference.md).

## 5. User checkpoint — HARD GATE

Present the ranked list (name, one-line rationale, evidence count, class, new-vs-improvement) plus the skipped-sources note, then **stop and ask**. Mirror the `generate-backlog` skill's rule: **never run `gh issue create` without explicit approval of the final list** — not in headless runs (hand off the list instead), not for "just the obvious ones". Support edits at the checkpoint and re-present if changes are material.

## 6. File and hand off

After approval only: file each approved recommendation through the `marketplace-feedback` skill flow (its labels, title convention, body shape — typically `type: feature`). Report every created issue URL. Natural downstream: an accepted recommendation becomes a skill-authoring task (house SKILL.md shape; Anthropic's skill-creator pattern for description tuning), and a batch of filed recommendations is wave fuel for the `wave-supervisor` skill.

## Cross-references

- `marketplace-feedback` skill — the filing mechanism; this skill only drafts.
- `generate-backlog` skill — origin of the confirm-before-filing checkpoint pattern; use it for product backlogs, this for skill-library gaps.
- `/plugin-feedback` command — structural plugin health; complementary, not overlapping.
- **#254 (deepagent skill management)** — the deepagent skill-management surface will delegate its "recommend" capability to this skill; keep the output contract stable for that consumer.
