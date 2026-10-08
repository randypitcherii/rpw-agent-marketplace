---
name: pain-interview
description: Runs a pain-first user interview and produces a structured pain ledger. Use when the user says "interview me", asks to discover product or workflow pain, wants to understand recurring friction, or needs evidence before generating solutions or a backlog.
---

# Pain Interview

Extract pain the user experiences; do not ask the user to design solutions. People
usually correct a wrong interpretation more accurately than they specify a desired
future. Use evidence-backed candidate interpretations, invite rejection, and stop as
soon as the pain model is useful.

Pipeline: thin context → adaptive interview → saturation decision → pain ledger →
separately tracked solution exploration.

## 1. Set the boundary

Identify the project, workflow, or product under discussion. Ask one focused intake
question only when the target is unclear.

Keep these streams distinct:

- **Interview method:** how the interview itself should improve.
- **Pain ledger:** what hurts, when, and with what consequences.
- **Solution exploration:** what might reduce the validated pain.

Do not silently turn the interview into solution design, implementation, issue filing,
or a UI project. Record those as separately tracked follow-up work after synthesis.

## 2. Gather thin context

Spend a short pass gathering evidence before the first round. Prefer the smallest
available set that can reveal pain:

- existing issues, retrospectives, and known workarounds;
- recent churn, abandoned branches, repeated fixes, and stale active work;
- prior user statements and concrete incidents already in the conversation.

Label observations as evidence and interpretations as hypotheses. Do not conduct broad
prior-art or solution research yet.

## 3. Run adaptive rounds

Ask two to four questions per round. Each question should contain:

1. a brief evidence cue;
2. a confident but easy-to-reject **candidate interpretation**;
3. overlapping options treated as **multi-select** when more than one can be true;
4. **free text** beside that question for correction or missing context.

Always make “wrong framing” or “none of these” available. Prefer pain-anchored
tradeoffs such as “which would you rather live with for another month?” over ranking
requests such as “is this priority order right?”

Mine both stated and revealed pain. Ask for a **concrete occurrence** when a theme has
no example. Seek root causes, triggers, consequences, and recurrence. Do not ask the
user to design solutions, name features, or approve an implementation during this
phase.

After each response:

1. update or merge pain records;
2. state what materially changed;
3. assess readiness as `continue | enough | complete`;
4. ask another round only when its purpose is explicit.

## 4. Stop at saturation

Use **two adaptive rounds** as the default maximum.

- `continue` — a contradiction or named **high-value gap** prevents a trustworthy
  synthesis.
- `enough` — core pain, triggers, consequences, and one concrete occurrence are known,
  and new answers mostly reinforce the model.
- `complete` — the ledger is synthesized and the user's corrections are incorporated.

**Diminishing novelty is a stop signal.** At `enough`, say “Enough signal to move
forward,” explain why, and make synthesis the primary action. One more round is
optional and must target a named gap. Never wait for the user to notice circularity.

## 5. Produce the pain ledger

Merge overlapping symptoms into root pains without discarding contradictory evidence.
For every record include:

- **Pain ID** — stable identifier such as `PAIN-001`.
- **Status** — candidate, active, improved, resolved, or rejected.
- **Confidence** — weak, medium, or strong, with the reason.
- **Recurrence** — one-off, repeated, or systemic.
- **Pain** — the user-centered problem, not a proposed feature.
- **Evidence** — statements, incidents, or repository signals.
- **Triggers** — conditions that produce the pain.
- **Consequences** — delay, risk, rework, cognitive load, or lost value.
- **Related pains** — links to records that share a likely root cause.
- **Corrections** — what the user rejected or reframed.

Keep detailed answers in the transcript; keep the ledger concise. Write checkpoints to
the user-approved durable destination when one exists. Otherwise present the complete
ledger in the conversation and ask before creating or changing an external artifact.

## 6. Hand off without blending streams

End with three compact outputs:

1. the pain ledger;
2. interview-method findings that should improve this skill or a dedicated experience;
3. a proposed, **separately tracked** solution-exploration brief.

The next brief should compare multiple solution families by expected impact, effort,
confidence, pain coverage, and tradeoffs. Do not begin it, mutate a backlog, or dispatch
work without the user's explicit approval. If repository work follows, use the existing
issue and development workflow rather than hiding it inside the interview thread.

## 7. Optional: run the rounds in a browser

A wall of multi-select markdown in a terminal is hard to follow, and one catch-all
correction field loses per-question context. When `projects/pain-interview-ui` is available,
offer the browser instead. The terminal path above stays fully supported.

```bash
uv run pain-interview-ui --fresh   # prints the URL to hand the user, and the session dir
```

Then, per round:

1. `POST <url>/api/round` with the round as JSON — `reflection` plus each question's `id`,
   `kind` (`single_choice` | `multi_select`), `claim`, evidence cue, and `options`. The page
   adds free text and "none of these / wrong framing" to every card itself.
2. `GET <url>/api/answers` once the user submits. Each entry carries `selected`,
   `none_of_these`, and `text`.
3. `POST <url>/api/ledger` with `{"records": [...]}` after merging. The side panel repaints
   without a reload.

Keep §4's saturation rule and §5's record fields exactly as they are — the surface renders
this skill, it does not change it. Routes, a worked round, and the port contract:
`projects/pain-interview-ui/README.md`.
