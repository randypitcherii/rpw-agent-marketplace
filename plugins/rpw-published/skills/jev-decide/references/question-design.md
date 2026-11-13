# Question design for System One models

What works and what does not, from live runs and from how small calibrated classifiers fail.

## Writing the questions

- **One fact per question.** "Is it urgent and in scope?" makes the model guess
  which half you meant. Split it into two `noul` questions.
- **Choice options must be mutually exclusive and collectively exhaustive.** Add an escape
  option (`other`, `nothing`, `never_started`) so the model is never forced into a
  wrong label. A 4B model asked to pick from options that overlap picks by position.
- **Write each criterion as something you can observe.** "it reported the task complete and
  asked for nothing" beats "done". Keep policy words (`archive`, `escalate`, `should`)
  out of the questions. Those decisions belong in the code that reads the answers.
- **Prefer several `noul` questions to one wide `choice`** when the labels are not truly
  exclusive. Use `choice` when exactly one must be true.
- **`score` levels are anchors.** Describe each level ("critical: needs action within
  hours"), use 3–5 levels, and read the expected `score` when you need a rank. It keeps
  the uncertainty: a 50/50 critical/high lands between the two.
- **Version the set** (`"version"` in the file). A stored answer from an older wording is
  stale and should be re-scored, not mixed in.

Set file shape (`ask --questions`, `eval --questions`):

```json
{"name": "ci-failure", "version": "2", "questions": {
  "flaky": {"type": "noul", "instructions": "Is this failure likely flaky?",
            "criteria": {"true": "timing, network, or ordering; passes on retry",
                         "false": "a deterministic assertion or compile error"},
            "abstain_below": 0.75},
  "area": {"type": "choice", "instructions": "Which area failed?",
           "criteria": {"infra": "runner, network, or credentials", "product": "the code under test", "other": null}}}}
```

`abstain_below` sets the threshold for one question and is stripped before the request.
Never send other extra keys: the route rejects fields it does not know with a 422.

## Building the state

- **Put hard facts in the state, but never ask about them.** Status, timestamps, and counts
  give the model context. Code still decides on them.
- **Keep it short and recent.** The session preset sends the last 3 messages at about 700
  characters each, keeping the head and the tail. More text adds noise faster than it adds
  signal, and every token counts against latency.
- **Use a JSON object for structure, a string for plain text.** Both are accepted.
- **Redact first.** The CLI strips common token shapes. Anything else sensitive is the
  caller's job.

## Thresholds and costs

Confidence is not accuracy until `eval` says so. Check ECE: if 0.8-confidence answers are
right 55% of the time, raise the threshold or reword the question. When errors cost
different amounts, use different thresholds. Missing a session that is waiting on you
costs more than one extra glance, so tune that question's threshold loose and the
"archive" path strict.

## The cascade

1. **Deterministic rules first.** Anything a field or regex settles costs nothing and never
   drifts. The session preset makes no model call for `failed` or a pending elicitation.
2. **System One for the semantic remainder.** It is cheap, fast, and calibrated enough to
   abstain.
3. **A large chat model for the `unsure` slice**, if it is worth the latency. Give it the
   same observation questions, not a free-form "what should I do?".
4. **A human for whatever is left**, shown the best guess and why it was unsure.

## More places it fits

- **Fleet and backlog triage**: route, effort, priority, and "already handled?" for tasks.
- **CI failures**: flaky versus a real regression, and which area owns it.
- **PR gates**: does the description state the problem, change, and test plan? Is this
  diff risky (migrations, auth, deletes)? Use `--fail-on-unsure` so the gate can say "look".
- **Alerts**: is this a duplicate of an open incident, and does it need someone now?
- **Agent self-checks**: before a turn ends, did I answer the question asked? Am I about to
  ask permission I already have?
- **LLM-as-judge rubrics**: `score` questions over an eval transcript, much cheaper than
  a generative judge.
- **Skill or tool routing**: which of N skills matches a request, using a `choice` with an
  escape option.

Where it does **not** fit: extraction (use a chat model or `ai_extract`), anything that
needs reasoning across long documents, and facts that are exact matches (use code).
