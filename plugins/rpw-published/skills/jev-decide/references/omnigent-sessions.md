# Classifying Omnigent sessions

```bash
uv run --no-project python scripts/jev_decide.py session --input "$T/info.json" --format text
```

From a checkout with the `rpw` CLI, `rpw sessions classify <session_id> --json` fetches a
live session and runs this same classifier on it, so no info.json is needed (#2437).

## Input

The input is `info.json` in the same shape as `omnigent-chief-of-staff`'s `fleet_report.py
--info`: `sys_session_get_info` objects, each carrying its history `items`. The file can be a
list, a `{"data": […]}` wrapper, or a map from session id to record. A separate
`sys_session_get_history` file (`{"conversation_id", "items"}`) merges into its record by id,
so you can pass both with two `--input` flags. A `workspace_git` probe from `fleet_report.py
--workspace-git` is honored when present.

## What the model sees

The model sees hard facts (title, status, runner, idle minutes, pending questions, recent
tool-call and error counts, `workspace_git`) and the **last 3 messages**. Each message is
clipped to about 700 characters, keeping the head and the tail, and common token shapes are
redacted.

## The questions (observations only)

| id | type | asks |
|---|---|---|
| `phase` | choice | working · waiting_on_background · waiting_on_human · blocked_external · finished · errored · never_started |
| `asks_human` | noul | does the last assistant message ask you for something? |
| `claims_complete` | noul | does it say the whole task is done? |
| `shipped` | choice | merged_or_deployed · pr_open · committed_unpushed · non_code_deliverable · nothing |
| `looping` | noul | is it repeating the same failing step or message? |
| `human_frustrated` | noul | did the human express frustration or repeat an ignored instruction? |

None of the questions ask what to do, and a test pins that.

## The rule table (first match wins)

| # | Condition | Action |
|---|---|---|
| 1 | `status=failed` (**no model call**) | `relaunch` in place; keep the worktree |
| 2 | pending elicitation (**no model call**) | `answer_human` |
| 3 | `running` | `intervene` if looping, else `leave_alone` |
| 4 | `asks_human`, or phase is waiting_on_human / blocked_external | `answer_human`, **even with the runner offline** |
| 5 | looping | `intervene` |
| 5a | `delivery.state=shipped`, phase not working / waiting_on_background | `archive` |
| 5b | `delivery.state=cleanup-pending`, same | `clean_up`: merged, but a branch, worktree or issue is left |
| 6 | phase `unsure` | `review`, showing the best guess and the reason |
| 7 | errored / never_started | `relaunch`, or `resume` if never started with a live runner |
| 8 | working (the turn ended mid-work) | `resume` |
| 9 | waiting_on_background | `resume` if the runner is gone; `nudge` if idle more than 30 min; else `leave_alone` |
| 10 | finished, but the workspace has WIP | `resume` |
| 11 | finished + `pr_open` | `track_pr` |
| 12 | finished + merged/deployed or non-code deliverable | `verify_then_archive` |
| 13 | finished + nothing or committed_unpushed | `resume`: a finished turn is not finished work |

**Delivery outranks the prose (#2449).** `rpw sessions classify` attaches a `delivery` fact read
from `git` + `gh` (states and probe: `libs/rpw_runtime/src/rpw_runtime/sessions/delivery.py`). It
is never part of the state the model reads. Rules 5a/5b fire only from it, so no model answer can
reach `archive`. `delivery.state=pr-open` replaces the model's `shipped` for rule 11, and `wip`
supplies rule 10's reason. `n/a` and `unknown` leave the model's answers in charge.

**Corroboration.** Before rule 4, `asks_human=true` forces phase to waiting_on_human. Before
rules 6–13, `claims_complete=true` + `asks_human=false` + a delivered `shipped` forces phase to
finished. The 7-way phase question is the least stable of the six. Two confident narrow answers
outvote it, and on the live sample that settled two `unsure` phases correctly.

`human_frustrated` and `looping` also appear as `flags` on every row. A human who keeps
repeating an instruction points to a skill or permission defect. Log it in the chief-of-staff
friction log.

## Measured (10 live sessions, 2026-10-17)

| Classifier | Result |
|---|---|
| `fleet_report.py` cascade | 6 `parked` (hidden by default), 4 of them waiting on the human; 2 waiting sessions read as `done_candidate` |
| `session` | 9 of 10 match a hand label. The miss was `intervene` where the label was `answer_human`, and both route to a human. The table was tuned on these same 10, so treat this as a smoke test, not a benchmark |
| per-call | 1–2 s, about 1.2–2k input tokens with order twins |

Grow a held-out set: run with `--log`, label the rows you correct, then run
`eval --preset omnigent-session`.
