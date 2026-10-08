---
name: notion-calendar-dupe-guard
description: Audit a Google Calendar for duplicate Notion Calendar "Busy" blocks and reset the blocking rule safely. Use when a calendar shows stacked or repeated Busy blocks, when Notion auto-blocking looks like it is amplifying events, or when asked to find, verify, or clean up duplicate availability blocks. Read-only with a hard no-delete boundary — it groups candidates by source identity and runs a disable/verify/re-enable reset; it never deletes events.
---

# Notion Calendar duplicate-block guard

**The pain:** Notion Calendar's auto-blocking writes "Busy" events into a Google calendar, and it can write **several** for one source event. Notion exposes the blocking rule in its UI but no API to inspect, deduplicate, or verify the Google events it produced — so a duplicate storm is invisible until a human scrolls their calendar and finds a week stacked four deep. Google Calendar is the authoritative source; ask it.

**The answer:** one read-only audit that groups destination events by Notion's private source tuple, and one reset runbook. 🚫 **Nothing here deletes calendar events** — there is no delete tool, by design.

## Start here

Audit a month of the calendar that receives the blocks:

```
google_calendar_audit_notion_duplicate_blocks(
  time_min="2026-09-01T00:00:00Z",
  time_max="2026-10-01T00:00:00Z",
  calendar_id="primary",
  include_candidates=false,
)
```

Read `summary.duplicateGroups`. **0 means clean** — and the counts reconcile (`eventsScanned` = grouped + `excludedCancelled` + `excludedUnmanaged`), so a zero is an answer, not a silence.

Non-zero: each entry in `duplicateGroups` names the source tuple, every destination `eventId`, the recurrence identity, and the time range. Re-run with `include_candidates=true` (or `source_event_id=<the tuple's event id>`) for the full rows.

## What counts as a duplicate

**Shared source identity — never shared title or time.** Notion stamps each destination block with the source event's identity in the event's *private* extended properties:

| Property | Meaning |
|---|---|
| `cron.syncOriginalAccountId` | which Notion-connected account produced the block |
| `cron.syncOriginalCalendarId` | the source calendar |
| `cron.syncOriginalEventId` | the source event |

A group is keyed on all three **plus** the recurrence instance slot (`originalStartTime`). Both halves are load-bearing:

- ⚠️ **Tuple alone over-reports.** With `singleEvents=true` a healthy weekly block expands into 40 instances that all share one source tuple. Keying on the slot too keeps them 40 separate singletons.
- ⚠️ **Title and time alone are not evidence.** Two 9am "Busy" blocks from two different source events are two real blocks. The audit reports them separately; a cleanup driven by title+time would delete a genuine one.

Cancelled events are excluded (`showDeleted=false` at the API, re-checked on `status`). Events with a partial or absent stamp are counted as `excludedUnmanaged`, never as candidates.

## The no-delete boundary 🚫

**There is no delete tool in the `google-calendar` MCP server, and adding one is a separate, explicitly-gated decision.** A test over the shipped source (`tests/test_notion_calendar_dupe_guard.py::TestNoDeletePath`) fails if a `DELETE` call ever appears.

To see what a cleanup *would* touch, screen one exact tuple:

```
google_calendar_screen_notion_cleanup_candidates(
  source_account_id="...", source_calendar_id="...", source_event_id="...",
  time_min="...", time_max="...",
)
```

It refuses a partial tuple, evaluates every predicate per candidate — exact source tuple, `confirmed` status, inside the time range, `Busy` summary, self organizer, no attendees, no conference data — fails **closed** on any timestamp it cannot parse, and marks exactly one member `retained`, so its output can never describe removing a whole group. It always returns `deleteEnabled: false`.

Export the screen output before acting on it. Then act **through the reset runbook**, not by deleting events.

## Fixing it: the reset runbook

Deleting duplicates treats the symptom; the blocking rule is what produced them. The reset — disable the affected direction, let reconciliation quiesce, verify one non-recurring event, re-enable — is in [`references/reset-runbook.md`](references/reset-runbook.md). Read it before touching the Notion UI: the order exists to protect the **unaffected** direction of a two-way personal/work setup, which a naive "turn it all off and back on" destroys.

## Reading the audit output

| Field | Use |
|---|---|
| `summary.duplicateGroups` | the triage number |
| `duplicateGroups[].duplicateCount` | worst-first; groups are sorted by this |
| `duplicateGroups[].recurringEventIds` | 2+ ids = duplicate *series*; empty = duplicate one-offs |
| `duplicateGroups[].instanceSlot` | `null` for one-offs, the `originalStartTime` for instances |
| `truncated` | `true` means the page budget was hit — narrow the window, the report is incomplete |
| `pagesFetched` | pagination actually ran; a 1 over a wide window is suspicious |

## Gotchas

- **Paginate or under-count.** One `events.list` page caps at 2500 events. `google_calendar_list_events` now takes `page_token`; the audit paginates for you to a bounded budget and sets `truncated` when it stops early.
- **Private properties are per-account.** They come back only for the account that wrote them, which is why a local cache is not a monitoring interface — and why the audit must run as the calendar's own owner.
- **One server-side property filter, not three.** The UC http_request transport carries query params as a map, so only one `privateExtendedProperty` constraint is reachable. `source_event_id` uses it to narrow; the exact three-key match is enforced locally.
- **Recurring sources need care.** Confirm on a **non-recurring** event first (the runbook says so) — a recurring one conflates "the rule is fixed" with "the expansion is fixed".

Server code and its tool table: `plugins/rpw-published/mcp-servers/google-calendar/`.
