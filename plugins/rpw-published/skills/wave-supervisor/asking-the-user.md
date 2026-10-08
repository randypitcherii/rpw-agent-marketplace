# Asking the user — the question tool, not prose

A question the user has to re-type an answer to is a question that stalls. The
supervisor's job is to make answering cheap, and that means `AskUserQuestion` (or
the host's equivalent) with real options — **not** a paragraph asking them to write
back. The only reason to write it as prose is that the tool **blocks**, and a
blocked supervisor is a stopped fleet.

So the rule is about *timing*, not format:

| When | What you do |
|---|---|
| Workers in flight, question can wait | **Do not call the tool.** Queue it: a **Decisions needed** block in `WAVE-STATE.md` and in the wave-issue checkpoint comment. |
| **The user signals availability** — "ready for questions", "give me the feedback", "what do you need from me", "resolve the outstanding questions" | **Call `AskUserQuestion` immediately**, draining the queue. Do not re-type the queued questions as prose in that turn; the signal *is* the permission to block. |
| A hard stop where nothing else is eligible (needs-input at the front, cap reached, unserializable merge) | **Call it unprompted.** Blocking costs nothing when there is nothing in flight. |

- **Queue questions tool-ready or not at all.** Each queued item owes a short
  header, the question, and **2–4 concrete labeled options** with what each one
  unblocks. If you cannot write the options, it is not a question yet — it is
  research you still owe, and shipping it as "thoughts?" pushes your work onto the
  user. This is the option-count rule for the whole file; every other mention of it
  points here.
- **Batch by what unblocks the most work — mid-wave.** While workers are in
  flight the wave has many checkpoints, so a queue longer than one call's worth
  drains in ordered batches across them, which still beats one-at-a-time round
  trips. **Close-out has exactly one checkpoint and no second round**, so batching
  does not apply there; the overflow rule under "Close-out" below replaces it.
- **Write the answers back** to `WAVE-STATE.md` and the wave issue as they land —
  an answer that lives only in the session dies with it.

## Close-out: the ask IS the delivery (#806)

A wave's leftovers used to arrive as a closing paragraph. Wave `2026-08-02` ended
with four human items three paragraphs apart, each phrased differently, in the same
voice and position as the status narrative around them — so the reader had to find
them first and then classify them. **At close-out, every item that needs the human
goes out as an `AskUserQuestion` call, never as prose.** The tool blocks on an
answer, so an unanswered item cannot scroll past; nothing else in a close-out
report does that.

**The prose report stays.** This is an addition to the delivery, not a replacement:
the narrative explains what the wave did, the questions decide what happens next.
Do not move status into the tool, and do not drop the report.

### The qualifying test — two columns, one line each

| Ask it | Leave it in the report |
|---|---|
| **A decision with materially different outcomes** — "dependabot #746 is red behind a config migration: leave open / close / migrate now?" | **Status** — "28 issues merged, CI green", budget spent, what was abandoned, what carries forward |
| **An action only the human can take** — "restart to load the upgraded plugins?"; "the first live run of the new command is yours" | **Anything you can decide yourself** — routine judgment calls are the supervisor's, and asking them hands your work back |
| **A parked needs-input item** — already a question with options, because parking one costs exactly that | **An FYI you want acknowledged** — that is status wearing a question mark |
| **A scope escape a worker surfaced** (#917) — it arrives with the options it did not choose between | **The wave PR merge** — you opened it, you merge it when green (#1878); asking is the old shape |

Two failure modes the columns are drawn against. The **2–4
concrete options** rule from the queueing section above is not waived here — close-out
is where an optionless item is most tempting, and it is still research you owe, not a
question. And if every option leads to the same work, it is status.

### The needs-input bucket is the queue — read it, do not re-derive it

`WAVE-STATE.md`'s `## Needs-input bucket` is this call's input. One entry per
question, already tool-ready. At close-out:

1. **Read the bucket verbatim** and ask what is in it. An item parked mid-wave is
   *delivered*, never re-summarized into a paragraph — re-deriving it is how
   correctly-parked items got flattened back into prose.
2. **Append the human items the wave produced after the last park** — a restart, a
   first live run, a red check left red on purpose.
3. **Write each answer back** to its bucket entry and to the wave issue as it
   lands, then act on it in the same session where the action is yours.

**Four questions, one call.** Four is the tool's ceiling, and a wave that needs
more rounds has stopped reporting and started interrogating. Over four: ask the
top four by what they unblock, **file the rest as issues**, and name those issue
numbers in the report. Never page through several rounds.

### Worked example — wave `2026-09-23-backlog`

Its bucket held three parked items and the wave produced no fourth human item (the
wave PR merge is step 5a's, not the human's). One call, three questions:

```text
AskUserQuestion(questions=[
  { header: "ADR policy",
    question: "ADR-2026-08-31 grants the diagram skill an exemption that names the
               retired \"Mono Bold\" theme (#1781). The decision is right, the name
               is dead, and your answer becomes the house rule for stale incidental
               references in landed ADRs.",
    options: [
      "Dated amendment — original text stays intact",
      "Correct in place — a theme name is incidental, not the decision",
      "De-name it — \"the diagram skill theme\" cannot go stale again" ] },

  { header: "HV cache",
    question: "high-voltage's PayloadCache revalidates in the background, spending
               the ~20/min search.messages quota it exists to protect (#1870).
               Which substrate? (The _restamp_ledger half ships either way.)",
    options: [
      "Keep PayloadCache, make the refresh quota-aware — smallest diff",
      "Suppression store for metered lanes — a hit costs zero Slack calls",
      "Measure real calls/hour on live prod first — cheap now, prod loops off" ] },

  { header: "Slack IDs",
    question: "#1213 needs the IDs of two shared Slack channels. Channels from
               another org are invisible to conversations.list, so the lookup
               table is the whole fix and only you can read them.",
    options: [
      "I will paste both IDs — the full table ships",
      "Ship the one known ID plus the post-by-ID gotcha, two TODO rows",
      "Skip #1213 this wave" ] },
])
```

Three things the shape is doing: each `header` is a short scan label, not a
sentence; each option says **what it unblocks**, so answering is a click; and the
one option that would otherwise read as "do nothing" ("measure first") carries the
note that the rest of its issue ships regardless.

## WHICH setbacks escalate — [`SKILL.md`](SKILL.md#escalation-triggers-pause-and-ask)

The seven triggers live there and only there (#1755). `SKILL.md` is the decision
surface a supervisor already has loaded; a second copy here was a second thing to
keep in step, and the two would diverge the first time one was edited.

This file owns the other half: **how** to ask once something has escalated — the
timing table above, tool-ready options, and writing the answer back to
`WAVE-STATE.md` and the wave issue.
