# Context Mode Activity Pattern (HN/GitHub)

## Purpose

Provide a lightweight, repeatable pattern for researching high-volume activity sources
(for example Hacker News and GitHub activity) without flooding agent context.

## When to use

Use this pattern when any source payload is large or uncertain in size, especially:

- Activity feeds (HN stories/comments, GitHub events/issues/PR streams)
- API responses with many items
- Command output that may exceed a few dozen lines

## Pattern

1. Collect raw data once.
   - Save source output to a local file in the current work area.
   - Prefer deterministic snapshots over repeatedly re-fetching live data.
2. Process with context mode tools.
   - Use `context-mode` execution tools for filtering, extraction, and summarization of large payloads.
   - Do not paste large raw output directly into chat context.
3. Emit a compact artifact.
   - Produce a short markdown note with: signals, evidence links, and action recommendations.
   - Keep the artifact focused on decisions, not raw logs.
4. Store findings in repo docs when durable.
   - Save durable research under `docs/research/` with a date-prefixed filename.
   - If the pattern changes team workflow, add or update an ADR.

## Minimum output contract

Every activity research run should include:

- Scope (time window + data sources)
- Top 3-5 signals
- Evidence pointers (URLs or file references)
- Suggested follow-ups

