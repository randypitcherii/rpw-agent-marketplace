# Morning prep report contract

The reader opens this before coffee and skims it in under a minute. Everything below serves that: one obvious identity, one bottom line, a short list of things to approve, and honest context.

## Guardrails

- **Read-only collection.** Calendar, mail, chat, trackers, and session lists are read, never written. Opening the finished file in a browser is the only side effect.
- **Proposals, not actions.** Every next action is a prompt the human may edit, copy, and run. Never imply it already happened.
- **State coverage.** Name each source checked, the window and timezone, and each source that was unavailable ("No calendar connected" beats a silently empty agenda).
- **Separate fact from inference.** "Run failed at 01:17 with `URLError`" is a fact; "likely connectivity" is an inference and says so.
- **No secrets or needless personal data.** Quote the decisive line of an error, not the log.

## Source discovery and access evidence

Missing native service tools are a routing question, not evidence that the account
is disconnected. When native tools are absent, load `mcp-cli`, use `rpw mcp`
(or its bundled launcher), and follow **servers → tools → call**. Inspect the live schema before
calling; never guess tool names or use an upstream API as a workaround. If the
bridge cannot be loaded or executed, record the exact failure and affected sources.

Before drafting, attempt a bounded read-only content request for each relevant
Calendar, Gmail, Slack, and task source; cap each call at **90 seconds** using the
caller's subprocess/tool timeout. Gather the target-day agenda, recent message
asks, and due tasks from working sources, not merely a connectivity probe. Read
message details when search returns only IDs; follow pagination as needed for the
claimed coverage or disclose the partial window. Do not mark messages read.
An auth-only success proves authentication, not content-read access.

Continue with working sources when another fails. An individual error such as
`HTTP 403: Request had insufficient authentication scopes.` belongs to that source,
not the whole report. Inspect error payloads even when an MCP envelope reports
`isError: false`. Never reuse a prior report's limitations as current access evidence
or substitute copyable scan prompts for gathering that is already possible.

Include a compact **Source access evidence** table under confidence & limits:

| Source | Tool / command | Checked at + timezone | Data window | Result / limit |
|---|---|---|---|---|
| Each relevant source | Actual read tool, discovery command, or unavailable bridge | Current observation timestamp | Exact window or n/a | Read succeeded (possibly empty/partial), failed with exact error, not installed after discovery, or not attempted with reason |

Keep unavailable counts **not measured**, never zero; an empty successful read is
different from an unattempted request. A discovery failure leaves access unknown,
not disconnected. Propose any install, OAuth, or scope recovery; do not perform it
in this read-only automation. No secrets or raw personal payloads in the evidence.

## Report structure (fixed order)

1. **Identity header** — eyebrow `Morning Prep · <Weekday, Month D, YYYY>`, the project mark, an `<h1>` bottom line, and a one-sentence dek. `<title>` is `YYYY-MM-DD · 🌞 Weekday Morning Prep`: ISO date first so tabs and browser history sort, then the exact automation name, so a tab says which schedule produced it.
2. **Coverage strip** — sources, window/timezone, limits.
3. **Today at a glance** — timed events and scheduled runs, each with status in words (scheduled / completed / failed / not checked).
4. **Priority map** — at most five numbered steps, in the order to do them.
5. **Suggested next actions** — one card per action with the fields below.
6. **What changed since the last prep** — the comparison chart and its equivalent table.
7. **Confidence & limits** — what could be wrong and what was not checked.
8. **Footer** — generated time and the read-only/proposal boundary.

## Next-action card fields

| Field | Required content |
|---|---|
| Priority | P0–P3 tag with a word label (never color alone) |
| Title | Verb-led action |
| Evidence | Source and time of the observation, plus caveat |
| Prompt | Editable `<textarea>` with a complete, copy-pasteable agent prompt |
| Copy button | Copies the textarea's current value; announces "Copied" via `aria-live` |
| Status | `Proposed — approval required` unless the human already approved it |

Cap at five cards; move the rest to a "later" line.

## Comparing day-over-day patterns

Follow the `dataviz` skill. The question the chart answers: *which recurring signals moved since the last prep?*

- **Form:** paired horizontal bars per signal — prior prep vs today — on **one shared zero-based count scale**. Direct value labels; prior uses an outlined/hatched mark and today a solid mark, so identity never depends on color.
- **Signals** must be counted the same way every day (e.g. decisions waiting, failed scheduled runs, open PRs awaiting review, meetings). Define each in the table.
- **Missing data:** show `not measured` text in place of the bar and in the table. Never draw it as zero, never interpolate, never carry yesterday's value forward.
- **Baseline:** with no prior prep, say "No comparable baseline yet — first prep with these definitions" and show today only. With fewer than three comparable preps, label the comparison **preliminary**.
- **Equivalent table:** a `<table>` with caption, `scope` headers, prior, today, change (▲/▼/= with the number), and definition/source. It is the accessible source of truth.
- **Changes are descriptive, not causal.** "Failed runs fell from 2 to 0" — not "the fix worked" — unless evidence says so.
- Read prior values only from prior dated reports or recorded counts; cite the file. Do not edit those files.

## Identity, favicon, and styling

- The header must be unmistakable among open tabs and other generated reports: Morning Prep eyebrow, project mark, `theme-color` `#984808` (registry value for `morning-prep`).
- **Favicon:** the report is a local file with no server-owned icon paths, so it embeds the project's own `favicon-32.png` as a base64 data URI (registered `inline` in `assets/project-icons/registry.json`). Never link another project's icon, an external URL, or a nonexistent `favicon.svg`. Regenerate with `scripts/build_icons.py` and re-embed with `scripts/inline_favicon.py`.
- Styles are inline, with values copied from `libs/ui/DESIGN.md` tokens (comment names the source) plus namespaced `--mp-*` identity tokens. Supports `prefers-color-scheme: dark`.
- Accessibility: semantic landmarks, logical headings, table captions/headers, visible `:focus-visible`, contrast ≥ 4.5:1, no whole-page horizontal overflow at 390px.
- No network requests: system fonts, inline script, no CDNs.
