# Self-improvement — the friction log and the harvest loop

The skill improves on **evidence it collects about itself**, on a cadence, through
the same review gate as any other change: a GitHub issue a human reads, then a PR
a human merges. It never edits itself.

Shape borrowed from two reference implementations and one house tool:

| Source | What was taken |
|---|---|
| `lukaszraczylo/claude-adam` | deterministic, zero-LLM-cost observation into a JSONL journal; analysis only on demand; a sliding window so stale friction stops counting; actioned entries archived out of the active journal |
| `AntaresYuan/claude-skill-iterate` | closed event vocabulary; a per-class threshold before anything is proposed; `safety_intentional` as the inverse of friction — a guardrail that fired is evidence *for* the rule, never a proposal to relax it; PR-not-commit as the unit of self-change |
| `wave-supervisor/retro-miner.md` | the output contract: one `retro-finding` issue per finding, `quick-win` when small, dedupe against open findings first |

## 1. Observe — log the snag when it happens

```bash
uv run --no-project python scripts/friction_log.py log <type> --detail "…" [--session ID] [--surface …] [--lesson "…"] [--skill <name> …]
```

Vocabulary (closed — `friction_log.py types` prints it; the test pins it):

| Type | Log it when |
|---|---|
| `probe_lied` | a field or tool result said one thing and the session was doing another (`idle` read as done, `runner_online` read as healthy, a "finished" claim with no PR) |
| `bulk_op_manual_loop` | you did the same thing to N sessions one at a time because no batch path existed or the documented one failed |
| `api_shape_drift` | a response was missing a field, had a new shape, or `fleet_report.py` exited with a payload error |
| `rename_refused` | a `PATCH`/`sys_session_rename` returned non-2xx or `renamed: false` |
| `reconnect_failed` | a wake/nudge POST returned 202 but history stayed frozen through two attempts |
| `user_correction` | the human said "no, that one is actually …" about a verdict the report gave |
| `missing_context` | the skill had to go read something (a brief, a doc, a route spec) the report or a reference file should have carried |
| `safety_intentional` | a confirm-before-mutate gate or a "never emits done" rule stopped an action and that was right |

`--lesson` is the highest-value field: one line of *what the skill should do
differently*. Three lessons that agree are an issue body; three details without
lessons are an anecdote.

`--skill` (repeatable) names the house skill whose guidance the snag implicates —
usually `omnigent-chief-of-staff` itself, sometimes a skill it composes onto
(`dispatch-launch` sent you down a dead path, `wave-supervisor`'s state table lied).
It is the input to the harvest's `skill:` line in step 3, so `report` can tell you
which skill to name without re-reading every event. Use the **directory name** under
`plugins/*/skills/`; omit it when the snag is an API shape, a network failure, or
anything with no skill to blame. A guessed attribution is worse than none.

**Log the correction, not the fix.** If the human corrects a verdict, log
`user_correction` with what they said. Do not also silently patch the cascade in
that session — the patch goes through the harvest so it gets a test.

## 2. Report — cluster on demand

```bash
uv run --no-project python scripts/friction_log.py report
```

Groups the last 30 days by type, prints count / first / last / recent details /
top lessons / sessions, and marks each class:

- **HARVEST** — count ≥ 3 and not a guardrail. File it (step 3).
- **watch** — under threshold. Leave it; it may never recur.
- **guardrail** — `safety_intentional`. Reinforcement, never a fix candidate.

Run `report` at the end of any chief-of-staff pass that logged something, and at
least weekly if the skill is in daily use. It is cheap; the cost is in ignoring it.

## 3. Harvest — one issue per class that crossed threshold

For each HARVEST class:

1. **Dedupe first.**
   `gh issue list --label retro-finding --state open --search "<type> chief-of-staff"`.
   An open finding for the same class gets the new evidence as a **comment**, not a
   sibling issue.
2. **File** (`issue-creation` shape; labels from the real set):
   - Labels: `retro-finding`; add `quick-win` when the fix is ≤ ~1 h and needs no
     design (a threshold change, a new row in the lying-probes table, a missing
     field in `fleet_report.py`).
   - Title: the improvement, imperative — "Treat a 45-minute `running` turn as
     `stale` in fleet_report", not "probe_lied happened again".
   - Body: the class, the count and window, the last five details verbatim, the top
     lessons, the sessions involved → the proposed change to this skill (which
     file, what rule) → the test that would pin it.
   - **`skill:` line** (#1960): one body line per implicated skill, from the `skills:`
     row `report` prints for the class:

     ```
     skill: omnigent-chief-of-staff
     ```

     A body line rather than a label, because the label set is already 81 entries.
     The weekly usage snapshot joins these into the rollup's outcome table, which is
     how a skill that *triggers* often is told apart from one that *helps* — a load
     count cannot. Use the directory name under `plugins/*/skills/`; a name matching
     no skill is dropped by the reader and reported as ignored. Omit the line when
     the class implicates no skill. Same convention as
     `wave-supervisor/retro-miner.md` and `periodic-review`; counting is
     forward-only, so nothing filed before it landed is backfilled.
3. **Archive** the harvested class so the active journal stays bounded and the next
   `report` does not re-flag the same evidence:
   `uv run --no-project python scripts/friction_log.py archive <type>`.
4. Report the filed issue numbers in the pass summary.

## 4. Apply — through a PR, never in place

The fix to the skill lands like any other change: an issue (from step 3), a branch,
a test that fails before and passes after, `make check`, a PR. Two constraints
`claude-skill-iterate` gets right and this skill keeps:

- **Never relax a rule that produced a `safety_intentional` event.** If the
  confirm-before-mutate gate stopped a bulk close, that gate is doing its job; the
  proposal is to make the *list* better, not to remove the gate.
- **Never widen the vocabulary casually.** A new event type is a schema change:
  add it to `EVENT_TYPES` in `friction_log.py` *and* to the table above *and* to
  the pinned test, in one PR, with the first real event that needed it.
- **Never name a script, tool, or field you have not confirmed exists.** A
  recovery script was cited across several passes as "the preferred wake
  mechanism" before anyone checked — it did not exist yet (#1825). `ls` the path,
  `grep` the field, or say plainly that you have not verified it. An assumed shape
  reported as fact is the `probe_lied` class pointed at this skill's own prose.

## What this is not

- Not a Databricks-backed improvement log. #1599 owns durable, queryable history;
  this JSONL is local, per-machine, and a candidate *input* to that when it lands.
- Not automatic. Nothing here edits `SKILL.md`, changes a threshold, or opens a PR
  without a human reading an issue first.
- Not a transcript. Details are one line, lessons are one line, and the secret
  filter refuses anything token-shaped. If you need the full story, the session
  id is in the event.
