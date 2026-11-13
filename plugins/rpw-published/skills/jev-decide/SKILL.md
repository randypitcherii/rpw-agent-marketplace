---
name: jev-decide
description: Typed, calibrated decisions from a System One model (OpenJev / TypeSafe Jev) — yes/no, pick-one, and score questions about any state, with abstention, option-order checks, and an eval loop. Use to classify an Omnigent session (stuck, waiting on you, resume, shipped, archive?), route or triage tasks, gate a step on a rubric, or before hand-rolling an LLM prompt that only needs a label. Trigger on "jev", "openjev", "system one", "ai_decide", "classify this", "is this session stuck".
---

# jev-decide

A System One model answers **typed questions about a state**: `noul` (the probability of
yes), `choice` (one label and a distribution), or `score` (an ordered scale). One call answers
1–10 questions in 0.5–2 s. Use it when you want a label, not prose. For SQL rows,
`ai_decide()` asks the same question types.

```bash
J="<this-skill-dir>/scripts/jev_decide.py"
uv run --no-project python "$J" models      # which models, on which workspaces
uv run --no-project python "$J" ask --state 'CI failed: timeout in test_upload after 600s' \
  --noul 'flaky=Is this failure likely flaky rather than a real regression?' \
  --choice 'owner=Who should look?:infra|test author|nobody' --format text
uv run --no-project python "$J" session --input "$T/info.json" --format text   # Omnigent
```

`--model auto` (the default) picks TypeSafe Jev when discovery finds it, else OpenJev.
Through the rpw LLM proxy, discovery spans the whole pool and Jev calls go only to the
workspaces that serve it. On 8 labeled sessions Jev got 8/8 actions, OpenJev 7/8. The CLI
is stdlib-only. Flags, transports and exit codes: [references/cli.md](references/cli.md).

## Four rules, each measured

1. **Ask for observations. Decide policy in code.** Ask what the state *says*, never what
   to *do*. Asked "what should the manager do next?", the model said `resume` for
   sessions that were plainly waiting on a human. Never ask about a fact you can read
   from a field.
2. **`unsure` is an answer.** Below `--threshold` (default 0.6) the answer is `"unsure"`,
   and the `best_guess` stays visible. Send it to a human or a bigger model. Never round
   it to a label.
3. **Check option-order stability (`--debias check`, the default).** Reversing the options
   flipped **4 of 10** live answers, one at 0.69 confidence. Each choice and score
   question is asked in both orders in one call, and the answer is `unsure` when the two
   disagree. `permute` averages the two orders instead. It scored worse (phase 0.62 vs
   0.88), because the reverse of a well-ordered list is a worse prior, not a neutral one.
4. **Eval before you trust a question set.** `eval --cases cases.jsonl` reports accuracy,
   coverage, Brier, ECE and the top confusions. Re-run it on every wording change. A
   re-score that shipped without one moved Drop from 184 to 68 and Do-now from 14 to 105,
   mostly under 60% confidence. `--log decisions.jsonl` builds the next eval set.

How to write the questions and the state, the decision cascade, and more use cases:
[references/question-design.md](references/question-design.md).

## Omnigent sessions

`session` reads the `info.json` that `omnigent-chief-of-staff` stages, and code maps six
observations to one action per row: `relaunch`, `answer_human`, `intervene`, `review`,
`resume`, `nudge`, `track_pr`, `clean_up`, `verify_then_archive`, `archive`, or `leave_alone`.
**`archive` and `clean_up` come only from a `delivery` fact** that `rpw sessions classify`
reads from `git` + `gh` (#2449). Saying "done" is not done; a merged PR is.
On a 10-session live sample, the fields-only cascade parked and hid 4 sessions that were
waiting on the human. This pass surfaced all four. The rule table and the questions are in
[references/omnigent-sessions.md](references/omnigent-sessions.md).

## Related skills

- `omnigent-chief-of-staff` — the fleet loop this adds a semantic pass to.
- `eval-patterns` — the house eval conventions `eval` follows.
