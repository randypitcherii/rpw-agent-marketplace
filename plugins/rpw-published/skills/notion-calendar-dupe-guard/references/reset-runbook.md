# Reset runbook — Notion Calendar blocking direction

Deleting duplicate blocks treats the symptom. The blocking rule produced them, and it will keep producing them. This is the reset.

🚫 **No-delete default.** No step below deletes a calendar event. The audit is read-only, the screen is read-only, and the repair is made in Notion's UI by toggling the rule — not by removing Google events. If you believe events must be removed, that is a separate, explicitly-gated decision with a human in the loop; export the screen output and stop here.

⚠️ **The order protects the unaffected direction.** A two-way personal/work setup has two independent blocking directions. One can be amplifying while the other is correctly protecting your availability. "Turn auto-blocking off and back on" destroys the healthy direction's state along with the broken one. Disable exactly the direction that is producing duplicates, and verify the other one still works before you re-enable anything.

## Before you start

- Know which calendar **receives** the duplicate blocks (the destination) and which calendar the source events live on.
- Notion Calendar's blocking rule is UI-only — there is no API for it. You will be clicking in the Notion Calendar app or web UI.
- Have the audit ready: `google_calendar_audit_notion_duplicate_blocks`.

## Procedure

1. **Capture evidence first.** Run the audit over the affected window with `include_candidates=true` and save the output to a file. Record `summary.duplicateGroups`, `summary.duplicateEvents`, and the `sourceTuple` of the worst group. This is your baseline — without it you cannot tell whether the reset worked.

2. **Identify the affected direction.** In the saved output, read `cron.syncOriginalCalendarId` from a duplicate group. That is the **source** calendar. The calendar you audited is the **destination**. The affected direction is `source → destination`. Write both down.

3. **Note the unaffected direction's current state.** In Notion Calendar's settings, find the blocking rule for the *opposite* direction (`destination → source`). Record whether it is on, and what its destination calendar and event title are. You will verify this is unchanged in step 6.

4. **Disable only the affected direction.** In Notion Calendar settings, turn off availability blocking for the `source → destination` rule from step 2. Change nothing else. Do not sign out of the account, do not remove the account, and do not touch the rule from step 3 — account removal resets both directions.

5. **Wait for reconciliation to quiesce.** Notion keeps reconciling after the rule is off. Do not judge the result immediately.
   - Re-run the audit over the same window. Record `summary.duplicateEvents`.
   - Wait 10 minutes. Re-run it. Record again.
   - Repeat until **two consecutive runs report the same counts**. That is quiescence. If counts are still moving after an hour, stop and report it — something is still writing, and re-enabling on top of that will confuse cause and effect.

6. **Verify the unaffected direction still blocks.** Create a short test event on the `destination` calendar — **non-recurring**, clearly named, 15 minutes, in the next day or two. Confirm exactly one block appears on the `source` calendar. If it does not, the disable in step 4 hit the wrong rule: undo it and restart at step 2. Delete your test event when done.

7. **Verify one non-recurring source event.** Create a short **non-recurring** test event on the `source` calendar. With the rule off, **no** new destination block should appear. Confirm that, then leave the event in place for step 9.
   - ⚠️ **Non-recurring is not optional.** A recurring test event expands into instances, and the expansion makes "the rule is fixed" and "the expansion is fixed" indistinguishable. One duplicate would hide inside an instance count.

8. **Re-enable the affected direction.** Turn the `source → destination` rule back on with the same settings it had. Do not add a second rule for the same pair — two rules on one pair is one way this duplicates in the first place.

9. **Verify with the event from step 7.** Within a few minutes, exactly **one** destination block should appear for it. Then run the audit with `source_event_id=<that event's id>` and confirm `summary.duplicateGroups` is 0 for it. Delete your test events from the source and destination calendars.

10. **Re-audit a forward window.** Run the audit over the next 30 days. Compare `summary.duplicateEvents` against the step-1 baseline. Historical duplicates from before the reset will still be present — that is expected, and it is what the cleanup screen is for. What must be 0 is duplicates for events created **after** step 8.

## If duplicates come back

Stop. Do not re-toggle repeatedly — each cycle writes more blocks and makes the history harder to read.

1. Disable the affected direction again (step 4).
2. Save the audit output and the `sourceTuple` of a group created after the reset.
3. Report it with the before/after counts and the timestamps of steps 4 and 8. A reset that does not hold is a Notion-side bug, not a configuration error, and the evidence is what makes that case.

## What this runbook does not do

- It does not remove existing duplicate blocks. Use `google_calendar_screen_notion_cleanup_candidates` to see and export what a cleanup would touch; it never deletes, and it always keeps one member of every group.
- It does not change the rule for any other account or calendar pair.
- It does not verify recurring source events. Confirm on a non-recurring one, then watch a recurring one over one full cycle before you call the setup healthy.
