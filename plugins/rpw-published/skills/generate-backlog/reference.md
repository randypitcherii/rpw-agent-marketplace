# generate-backlog — reference

Templates and a worked example for the generate-backlog skill. The dispatch *mechanics* (tool schema, background/read-only rules, Context block, Result Format) come from the `subagent-dispatch` skill — this file only carries the PM-specific payload.

## Proposal shape (fixed — every proposal, verbatim headings)

```markdown
### <Proposal title — imperative, one line>

**Problem** — Who hurts, when, and why the status quo is insufficient. 2–4 sentences,
grounded in something observed (repo docs, issue history, domain research), not invented.

**Scope sketch** — The smallest coherent implementation: components touched, rough
approach, what is explicitly OUT of scope for v1.

**Acceptance** — 2–5 checkable criteria. Each one is verifiable by a reviewer without
asking the author ("`make check` passes", "a user can X from Y", "docs section exists").

**Safety** — Constraints the implementation must respect: destructive-action gates,
secret handling, permission boundaries, data exposure. Write "none identified" rather
than omitting the section.

**Dependencies** — Other proposals in this batch (by title), existing issues (by #),
and missing credentials/infrastructure. If a dependency is blocked, say so: this
proposal files as *blocked* and must not be dispatched until the blocker clears.
Write "none" rather than omitting.

**Size** — S (≤ half a day) / M (a day-ish) / L (multi-day; consider splitting —
propose the split if obvious).

**Dedupe check** — Existing issue numbers reviewed as near matches, and the verdict:
"no overlap", "extends #N (delta: …)", or "duplicate of #N — dropped".
```

## PM-agent prompt template

Dispatch per the `subagent-dispatch` skill's research-task conventions (`description: "pm-{lens-slug}"`, read-only, background, one message for all lenses). Prompt body:

```
You are a product-manager agent generating engineering-backlog proposals for {owner/repo}.

## Product goal
{one-paragraph goal, verbatim from the user}

## Your lens: {lens name}
{2–3 sentences: what angle of the goal you own, what you explicitly leave to the
other lenses. Propose ONLY within this lens.}

## Context
{Standard Context block: what the dispatcher has read, label conventions found,
constraints the user stated.}

## Existing issues (dedupe baseline — all states)
{paste of `gh issue list --state all --limit 200 --json number,title,state,labels`
output, or a path the agent can read}

## Research sources
Use the Glean MCP tools for domain research IF they are available in your
environment. If not available or auth fails, do NOT stop or ask — research from the
repo itself (README, docs/, ADRs, issue + PR history, code) plus web search if you
have it, and state "researched from repo-local sources (+ web) only" in your result.

## Requirements
- Return 3–6 proposals, each in EXACTLY the proposal shape provided below.
- Dedupe: check every proposal against the existing-issue list, including closed
  issues; record the verdict in the proposal's Dedupe check field.
- Declare dependencies on other proposals, existing blocked issues, and missing
  credentials. Propose credential-blocked work as blocked; don't omit it.
- You are read-only: no file edits, no `gh issue create`, no comments on issues.
  Proposals come back only in your final message, using the standard Result Format.

## Proposal shape
{paste the proposal-shape template from this file}
```

## Synthesis checkpoint format

Present the post-synthesis list to the user as a ranked table before any filing:

```
| # | Title | Priority | Labels | Size | Depends on / blocked by | Lens(es) |
|---|-------|----------|--------|------|-------------------------|----------|
| 1 | Add ingest CLI for reading notes | P1 | type: feature | M | none | automation |
| 2 | Topic rollup view | P1 | type: feature | M | #1 (ingest) | discovery |
| 3 | Library sync (write-back) | P2 | type: feature, blocked | L | Library API access | automation, discovery |
```

Then ask explicitly: which to file as-is, which to edit, which to drop. Only after that approval do any `gh issue create` commands run.

## Worked example (condensed)

Origin run: a personal reading-notes repo with the goal *"turn raw highlights into a searchable knowledge library with minimal manual upkeep."*

- **Lenses derived (2):** *automation workflows* (getting notes in and processed with zero friction) vs *knowledge discovery* (what the processed data can answer). Complementary: one owns input/pipeline, the other owns output/insight; neither pads the other's space.
- **Dispatch:** two PM agents, one message, background, Sonnet, `pm-automation-workflows` / `pm-knowledge-discovery`. Each got the goal, its lens, the full issue snapshot, and the proposal shape.
- **Dedupe in action:** the discovery agent found its "stale-topic digest" idea was ~80% an existing open issue; it returned the 20% delta as an extension citing the issue number instead of a duplicate.
- **Dependency declarations in action:** the automation agent proposed a library write-back but had no way to verify API access; it filed the proposal as *blocked on library credentials* rather than dropping it — the synthesis step ranked it low and labeled it blocked.
- **Synthesis:** 9 raw proposals → 7 after cross-lens merge (both lenses independently proposed a notes-normalization step; merged, keeping the automation agent's scope sketch and the union of acceptance criteria) → ranked with the normalization prerequisite first.
- **Checkpoint:** ranked table presented; user dropped one, downgraded one to P3, approved the rest. Only then were issues filed with the repo's `type:`/`priority:` labels.
- **Hand-off:** the filed set was offered to the `wave-supervisor` skill as a bounded wave, with the blocked library-sync item excluded from dispatch by its label.
