# Status updates — the five-state convention

Recurring updates and final answers look the same, so the reader either reads every
progress ping (and burns attention) or skims them all (and misses the one that says
*done* or *I need you*). A loop that posts twelve identical-looking checks trains the
reader to ignore the thirteenth — which is the one that mattered.

The fix is one **status line** with a **closed set of five states**, plus a shape rule
that makes open and terminal updates structurally different.

## The status line

Line 1 of every recurring or automated update, nothing above it:

```
<emoji> <STATE> — <subject> · <delta> · <next or position>
```

- **`STATE` is UPPERCASE, and it is the authoritative signal.** Not the emoji, not
  bold. Slack `mrkdwn` has no `**bold**`; plain-text notification bodies have no
  markdown at all. Uppercase survives every renderer.
- **Emoji is redundant reinforcement**, never the only carrier of meaning
  (WCAG 1.4.1 — never convey information by glyph or color alone).
- **` · ` separates fields**, not `|` (breaks markdown tables) and not `—` (already
  the state/subject divider).
- **Status line first** because push notifications truncate near 200 characters and
  Slack previews only the first line. Anything after may never be read.

## The five states

Two open, three terminal. Nothing else — a sixth state is a field on one of these.

| Emoji | State | Meaning | Shape |
|---|---|---|---|
| ⏳ | `WORKING` | still running, nothing needed | 1 line |
| ⚠️ | `NEEDS YOU` | blocked on a human decision or input | 1 line + a Decisions block |
| ✅ | `DONE` | finished, goal met | block |
| ❌ | `FAILED` | finished, goal not met | block |
| 🛑 | `STOPPED` | ended deliberately without finishing (budget, cancel, park) | block |

**`FAILED` vs `STOPPED`** is the distinction automation keeps getting wrong: a job
that hit its cost cap did not fail, and a crashed job was not stopped. Collapsing
them makes every alert equally urgent, which is the same as no alerts.

**No-change is a field, not a state.** A quiet check is
`⏳ WORKING — nightly sync · no change since 14:02 · check 3 of 12`.

**🚫 is deliberately not a status token** — house style already reserves it for
prohibitions ("never do this"). Reusing it for failure would collide on every page
that carries both.

## The shape rule — open is one line, terminal is a block

This is what defeats habituation, and it uses only blank lines and line counts, so it
survives every renderer including plain text.

- **Open states (`WORKING`, `NEEDS YOU`) are exactly ONE line.** No body, no heading,
  no bullets. A recurring update that grows a body stops being skippable.
- **Terminal states (`DONE`, `FAILED`, `STOPPED`) are a block**: one blank line, the
  status line, then 1–4 lines of body. Nothing after the body.
- **`NEEDS YOU` is the one open state allowed a follower** — the labeled
  **Decisions needed** block the core rules require. The status line still stands
  alone on line 1.

A reader scanning a column of updates sees an unbroken run of single lines, then one
that has mass. The conclusion is unmistakable without reading a word.

## Never use `---` as a separator

Two independent reasons, both silent failures:

- **Slack renders `---` literally.** It has no thematic-break syntax; you get three
  hyphens in the message.
- **In CommonMark, `---` directly under a line of text turns that line into a
  setext `<h2>`.** Your separator eats the line above it and changes its meaning.

Separation is a blank line plus the next status line. That is enough.

## Examples

Loop / watchdog — three checks and a conclusion:

```
⏳ WORKING — CI on #1712 · 4 of 7 checks green · next poll 90s
⏳ WORKING — CI on #1712 · no change since 09:14 · next poll 90s

✅ DONE — CI on #1712 · all 7 checks green · ready to merge
Ran 12m. `make check` and the two mocked MCP suites passed.
```

Background worker, deliberate stop:

```
🛑 STOPPED — worker #1712 · cost cap $5.00 reached at step 4 of 6 · nothing merged
Worktree left in place at `…/worker-1712`; branch has 2 commits.
Resume with `make build-claim ISSUE=1712` then rerun step 4.
```

Blocked on a human:

```
⚠️ NEEDS YOU — schema migration · blocked at step 2 of 5 · pick a backfill window

**Decisions needed**
- Backfill now (≈40 min of write contention) or tonight at 02:00 (no contention,
  ships a day later)?
```

Failure:

```
❌ FAILED — nightly sync · exit 137 at 03:11 · no rows written
OOM-killed on the `accounts` batch; last good run 2026-09-08.
Fix: raise the container limit or shrink the batch, then rerun `make sync-nightly`.
```

## Alternatives considered

**Two fields instead of one token.** Every mature system splits phase from outcome —
GitHub check runs carry `status` *and* `conclusion` (setting a conclusion is what marks
a run complete), Cursor emits a status event and a separate result event, and Devin
shows the failure mode of one axis: its `finished` lives *inside* `running`, so a
consumer reading `status` alone cannot tell done from in-flight. A prose update has no
second field to populate. **The shape rule is our second axis** — mass, not vocabulary,
carries finality, which is why it must hold even when a renderer drops every glyph.

**ASCII tokens (`[OK]`, `[FAIL]`) instead of emoji.** Zero rendering divergence, and
the closest precedent is journald's leading `<0>`–`<7>` prefixes. Rejected because
house style already uses functional emoji as signposts, and the UPPERCASE token gives
us the ASCII-only signal for free — a reader whose font or screen reader drops the
glyph still reads `FAILED`.

**Emoji at the end of the line.** UK GCS accessibility guidance says put emoji at the
end, cap them at three, and never repeat one; NVDA only speaks emoji names when the
user opts in, so a leading glyph can be announced, mispronounced, or skipped. We keep
it leading anyway, deliberately: a scanned column of updates sorts on its first
character, and the notification preview truncates from the right. The compensations are
the ones that guidance actually asks for — **one** emoji per update, never mid-sentence,
and the word immediately after it carries the whole meaning.

## Cross-harness portability

Verified against `docs/architecture/harness-matrix.json` (claude code, codex cli,
cursor cli, pi, hermes) and the Omnigent bundles at `agents/omnigent/`. The
convention deliberately uses **only** features every one of them renders:

| Feature used | Why it is safe |
|---|---|
| UPPERCASE state token | plain text — renders identically everywhere, including notifications |
| Blank line + line count | structural, not syntactic; no renderer can drop it |
| ` · ` (U+00B7) | plain punctuation; no markdown meaning in any dialect |
| Five emoji, all E0.6–E1.0 | ✅ ❌ ⏳ 🛑 are `Emoji_Presentation=Yes` and need no variation selector; ⚠️ carries VS16, as house style already does. No ZWJ sequences, skin tones, or flags — those decompose into visible garbage where the font is older ([UTS #51 §2.2](https://www.unicode.org/reports/tr51/)) |

**Never pad a status line into columns.** Emoji cell width is genuinely unresolvable
by the writer: UAX #11 says the property "is not intended for use by modern terminal
emulators without appropriate tailoring", one grapheme measured 2–6 cells across
shipping terminals, and ⚠️ is width-1 in `EastAsianWidth.txt` but renders 2 cells with
VS16. Fields are separated by ` · `, never by alignment.

**Known limitation:** 🛑 / ❌ / 🚫 read similarly at small sizes and to color-blind
readers. That is why the UPPERCASE token is the authoritative signal and the emoji is
redundant — a reader who cannot tell the glyphs apart loses nothing.

**Adjacent, not conflicting:** [`wave-pr-template.md`](../../wave-supervisor/wave-pr-template.md) uses ‼️ for a surprise and ⏭️ for
deferred work *inside a body*. Those are body annotations, not status tokens; the five
states own line 1 and nothing else does.

## Who inherits this

Do not restate these rules. Reference this file:

- `communication/SKILL.md` Rule 8 — the pointer every deliverable sees.
- `references/core-rules.md` — the one always-on bullet, propagated to
  `agents/omnigent/house-standard.md` and all five bundles by
  `make sync-communication-core`.
- Every workflow that emits recurring or terminal updates — wave tallies, dispatch
  reports, `/build` completion, worker returns, scheduled-job notifications. The gate's
  `CONSUMERS` list is the authoritative enumeration; this list is illustrative.

Gate: `tests/test_status_update_convention.py`.
