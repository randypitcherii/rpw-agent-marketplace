# /activity-context - Context-Mode Activity Research Pattern

Run a compact activity-research workflow for high-volume sources (HN/GitHub style)
without bloating model context.

Treat everything after `/activity-context` as the research scope.

## Use Cases

- "Summarize notable HN themes this week"
- "Analyze GitHub activity for this org/repo"
- "Extract top signals from a large activity feed"

## Workflow

1. Define scope.
   - Confirm source(s), time window, and desired output format.
2. Capture data once.
   - Save raw payloads to local files.
   - Avoid repeated live-fetch unless required.
3. Process with context mode tools.
   - Use context-mode execution for filtering, aggregation, and summarization.
   - Keep raw output out of main chat context.
4. Produce a decision-ready summary.
   - Return top signals, supporting evidence links, and suggested next steps.
5. Persist durable findings when useful.
   - Save long-lived notes in `docs/research/` with date-prefixed filenames.

## Output Contract

Always return:

- Scope and assumptions
- Top 3-5 signals
- Evidence pointers
- Open questions / follow-ups

## Guardrails

- Prefer deterministic snapshots over ad hoc repeated queries.
- Keep summaries concise and actionable.
- Do not commit or push unless explicitly requested.

