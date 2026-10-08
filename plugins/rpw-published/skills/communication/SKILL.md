---
name: communication
description: The house communication standard — structure, ordering, length, visuals, and action-shaping for everything a human reads. Load before writing session summaries, Slack messages, GitHub issues or PRs, docs, or reports. Trigger on "too verbose", "tighten this up", "make this skimmable", "communication standards", or ADHD-friendly output. Covers problem-before-solution and answer-first ordering, skimmability, length budgets, when a visual earns its cost, and output an ADHD reader can act on.
---

# Communication — the house standard

Three failure modes cost the reader more than anything else we write:

1. **Volume.** Replies, Slack posts, and issues run several times longer than the information they carry — preamble, restated requests, tool narration, recaps. The reader skims, misses the load-bearing line, and pays for every wasted token twice: at generation, then as context in every later turn.
2. **Order.** Solutions arrive before the problem they solve, so the reader cannot map new information onto known pain — they re-read, or miss that you are solving the wrong problem.
3. **Shape.** Correct writing that is still unusable: no obvious first move, no idea which step we are on, no sense of how long anything takes. The reader has ADHD, and knowing the answer is not doing the answer.

This skill governs the layer between sentences and rendering: what to say, in what order, at what length, and when a picture beats prose. `simple-english` owns the sentence level; `slack-formatting`, `doc-styling`, `issue-creation`, and `project-readme` own their surfaces' mechanics and inherit these rules.

## Rule 1 — Problem before solution

Open every deliverable that proposes or explains something with, in order:

1. **The problem** — what hurts, who it hurts, one concrete example.
2. **Why it matters** — the cost of leaving it alone, in one line.
3. **The answer** — what you did or propose.
4. **The detail** — ordered so the reader can stop anywhere and lose only depth.

A reader maps new information onto pain they already know: lead with the problem and they know within two lines whether you are on the same page. Skip steps 1–2 only when the problem is the reader's own words from this conversation — then open with the answer.

## Rule 2 — Answer first, ceremony gone

The first sentence answers "what happened" or "what should I do". Everything after it is optional depth. Cut ceremony, not reasoning:

- **No preamble or recap.** Do not restate the request, announce what you will do, or summarize what you just said.
- **No tool narration.** The calls are visible in the transcript; do not describe them.
- **State each fact once.** Do not re-derive what the conversation already established.
- **No hedges or filler** — "it's worth noting", "basically", "simply", "I should mention". The test: a sentence that would fit unchanged in a different conversation carries no information. Delete it.
- **Quote the decisive line, not the log.** Cite `path:line`; never paste a file, diff, or log the reader can open.

"Concise" does not mean "short". The reasoning behind a non-obvious choice is what the reader cannot reconstruct — keep it, delete the ceremony around it.

## Rule 3 — Skimmable by construction

The headers and bold words alone must tell the whole story. Mechanics:

- **Headers carry conclusions.** "Fix the retry loop before scaling" beats "Recommendations". Reading only the headers must give 80% of the message.
- **Bold the scan-target** in each bullet and paragraph — the noun or verdict a skimming reader hunts for.
- **Paragraphs of four sentences or fewer**, one topic each, blank line between.
- **Lists for three or more parallel items**; prose for connected reasoning. Never a list of one.
- **Tables for enumerable facts** (options, statuses, name → value). Explanation lives in the surrounding prose, not in cells.
- **Functional emoji as signposts** — ✅ ⚠️ 🚫 🔴 at section or bullet heads, so the reader sorts items at a glance. Never decorative, never mid-sentence. House style *wants* these; do not drop them for formality.

## Rule 4 — Length budgets per surface

Budgets are defaults, not caps on substance. When content overflows, use the valve — do not inline it.

| Surface | Default budget | Overflow valve |
|---|---|---|
| Chat answer | 1–5 sentences, prose | Offer depth: "want the full trace?" |
| Chat work report | ≤ 1 screen: verdict, what changed, how verified, risks, decisions | Link files and issues |
| Slack message | ≤ 10 lines in the parent | Details in the thread; big content in a linked doc |
| GitHub issue | Problem / impact / desired shape / acceptance, each a short paragraph or list | Link evidence; never inline logs |
| PR body | What + why in ≤ 10 lines, then bullets | Commits and linked issues carry depth |
| Doc / report | No cap — every section obeys Rules 1–3 | Appendix or subtab |

## Rule 5 — A visual must earn its cost

Build a visual **unprompted** when prose is the worse tool: **structure or flow among 3+ interacting parts** → diagram; **comparison across 2+ dimensions** → table (cheapest — reach for it first); **trend, distribution, or ranking** → chart; **before/after topology** → paired diagram or table.

Take the **cheapest rung that works**: markdown table → inline mermaid/ASCII → `diagram` skill PNG → `dataviz` chart → HTML artifact. One visual per deliverable unless asked for more.

**Borderline case → offer, don't build.** One line — "a diagram would show this dependency loop in one glance; want it?" — beats both spamming visuals and making the reader specify one.

## Rule 6 — Decisions never hide in prose

Anything that needs a human decision or action goes in a labeled **Decisions needed** block (or through `AskUserQuestion` where the harness supports it), each item with its concrete options — never scattered through narrative. Status stays prose; decisions get structure. (Refs #806.)

## Rule 7 — Shape output so it can be acted on

The reader has ADHD, so structure carries as much weight as content. Read
`references/adhd-reader.md` before any multi-step plan, status update, or debugging report.
Load-bearing:

- **Lead with the next action** when the deliverable exists to get something done — command,
  path, or snippet on line one. This *outranks* Rule 1: problem-first is for proposing and
  explaining, not for "here is what to run".
- **Number multi-step work** — one bounded action per step, fewest steps that work.
- **Restate position every turn** — "step 3 of 5 done: schema updated. Next: backfill", or
  let a todo tool carry it.
- **Time estimates in concrete units**, never "some work"; aimed at whoever executes.
- **Finished work stated concretely** — what now works, and how to see it.
- **Errors matter-of-fact** — cause and fix, no "uh oh", failing line quoted exactly.
- **Cap lists at five**, then split do-now vs later; suppress tangents — finish the first
  thing, offer the second as its own question.
- **One concrete next action** under two minutes when anything is open: "run `make check`
  and paste the first failure", not "let me know".

**When these bend:** "explain this to me" runs as long as the topic needs; a debug spiral
gets one diagnostic question, not another patch; and when a rule would delete the answer,
the answer wins and only the shape stays.

## Rule 8 — Status updates use the five-state line

Recurring updates and conclusions must not look alike, or the reader skims both — and
skims the one that mattered. Every automated, looping, or long-running update opens
with a **status line**: `<emoji> <STATE> — <subject> · <delta> · <next>`, `STATE` one
of exactly five — ⏳ `WORKING`, ⚠️ `NEEDS YOU`, ✅ `DONE`, ❌ `FAILED`, 🛑 `STOPPED`.
**Open states are one line; terminal states are a block**, and `---` is never the
separator. The UPPERCASE token carries the meaning, never the emoji alone.

Full rules and examples: [`references/status-updates.md`](references/status-updates.md).

## Do NOT compress

Full, explicit prose — no trimming — for:

- Confirmations of **destructive or irreversible actions**, and anything outward-facing (publish, send, merge to a release branch).
- **Security warnings** and risk callouts.
- **Ordered procedures** where dropping a connective makes the order ambiguous.
- **Quoted errors and evidence** — quote exactly, never paraphrase.

## Self-check before delivering

1. Does the first sentence carry the verdict?
2. Read only the headers and bold text — does the story survive?
3. Does the problem appear before the solution?
4. Delete-test the first and last paragraph — preamble and recap live there.
5. Is any human decision buried in prose? Move it to a Decisions block.
6. Could a table or diagram replace a paragraph? Take the cheapest one that works.
7. First and last line only — does the reader know what just happened and what to do next? Multi-step work: is position stated, with a time estimate?

## Composition

- `simple-english` — sentence-level clarity (word choice, tense, sentence limits). Apply it inside this structure.
- `slack-formatting` / `doc-styling` / `issue-creation` / `project-readme` / `changelog-release-notes` — surface mechanics and templates. They inherit these rules and win on rendering details.
- `diagram` / `dataviz` — producing the visual once Rule 5 says it earns its place.
- `references/adhd-reader.md` — Rule 7 in full: its five reading constraints,
  before/after pairs, override cases, pre-send deletion pass. Adapted from
  [`i-have-adhd`](https://github.com/ayghri/i-have-adhd) (MIT).
- `references/status-updates.md` — Rule 8 in full: states, shape rule, examples,
  renderer hazards. **Canonical**; never restate it elsewhere.
- `references/core-rules.md` — the always-on core; **canonical**. Edit it there, then
  `make sync-communication-core`.
