---
name: doc-styling
description: Formatting and voice rules for authoring or editing Google Docs and customer-facing prose. Trigger on "write this up as a customer doc", "draft a gdoc", "format this doc", "email-style formatting", or editing any Google Doc tab or outbound customer write-up. Encodes email/technical-note structure (real headings, dashed + nested bullets, bold scan-targets, inline code, emojis), customer-doc voice, pain-avoided framing, and render gotchas. NOT for plain code docs, READMEs, or code comments.
---

# Doc Styling — customer-doc & gdoc email-style formatting

Consistent formatting and voice for prose deliverables — customer-facing write-ups,
Google Docs, and internal technical notes. Apply these rules **every** time you author or
edit such a doc so styling stays uniform across tabs and across sessions (the failure this
skill exists to prevent: one tab follows the format while a sibling tab, written in a
different session, ignores it entirely).

## When to invoke

**Explicit triggers:**
- "write this up as a customer doc"
- "draft a gdoc" / "create a Google Doc for X"
- "format this doc" / "clean up this doc's formatting"
- "email-style formatting" / "make this scannable"
- editing **any** Google Doc tab or outbound customer-facing write-up

**Proactive use:** reach for these rules whenever you're producing prose a human will read
as a deliverable — a status doc, a recommendation memo, a customer summary, a technical note.
Structure, ordering, and length of the content itself (problem-before-solution, budgets,
when a visual earns its place) come from the `communication` skill; this skill renders it.

**NOT for:** plain code documentation, READMEs, API reference, inline code comments, or
commit/PR bodies. Those have their own conventions; don't impose email-style section tags on them.

## Format — email / technical-note style

Write for scanning, the way a well-structured internal email or technical note reads.

- **Real headings, not bold paragraphs.** Use actual H2 / H3 heading levels (`##`, `###`)
  so the doc has a navigable structure — never fake a heading by bolding a normal line.
- **Headings space the sections, not blank lines.** In the house style a heading's own
  space-above separates it from the text before it (`house_style.json`). Do not add empty
  paragraphs next to headings; `gdocs_lint` reports them as `blank.adjacent_heading`.
- **Dashed bullets** (`-`) for lists. Keep each bullet to one idea.
- **Nest sub-points instead of flattening them.** When several bullets are details of one
  idea, indent them under it — 2–3 levels of nesting is normal and correct, not a smell. A
  flat list forces the reader to re-derive the grouping you already knew.

  Before — flat, the reader has to work out which lines belong together:

  ```markdown
  - **Cost** is driven by cluster size
  - Autoscaling is off
  - Node type is memory-optimised
  - **Latency** is driven by file layout
  - Small files dominate
  ```

  After — the grouping is visible:

  ```markdown
  - **Cost** — driven by cluster size
    - Autoscaling is off
    - Node type is memory-optimised
  - **Latency** — driven by file layout
    - Small files dominate
  ```

- **Bold the scan-target in each bullet.** Lead each bullet with the noun/phrase a skimming
  reader is hunting for, in **bold**, then the detail. The reader should get the gist from
  the bold words alone.
- **Inline `code` for identifiers.** Wrap function names, flags, region names, table names,
  file paths, and other literal tokens in backticks — e.g. `us-west-2`, `create_deep_agent`,
  `DATABRICKS_CONFIG_PROFILE`. Signals "this is an exact string," not prose.
- **Links as markdown** — `[label](url)`, never a bare pasted URL or "click here."
- **Functional section-tag emojis only.** A small, consistent kit used as section tags to
  signal *what kind of content* follows — not decoration:
  - 📍 current state / where things stand
  - ⚠️ pain / risk / caveat
  - ✅ recommendation / decision
  - 📋 list / checklist / steps
  - 📊 data / metrics
  - 👥 owners / people
  - Never **cheerleader emojis** (🎉🚀🔥💪✨). They add noise, read as filler, and undercut
    a serious deliverable. One functional tag per section header at most.

## Voice — customer-doc

- **Concrete nouns over jargon.** Say "VM" not "SKU," "the nightly job" not "the scheduled
  compute artifact." Prefer the word the reader already uses for the thing.
- **Soften asks with "Optional."** When you suggest something the customer *could* do but
  isn't required, label it `Optional` so it doesn't read as a demand or a gap they're failing.
- **Root tabs are summaries; detail lives in subtabs.** The top-level tab should read as a
  standalone executive summary. Push supporting detail, tables, and references into sub-tabs
  and link/refer to them — don't dump everything on the front page.
- **Light Title Case for section labels.** Section labels get gentle Title Case ("Current
  State," "Recommended Next Steps") — not ALL CAPS, not sentence-case-only.

## Framing

- **Pain-avoided framing, in the customer's own words.** Describe what the customer *stops
  suffering* — the concrete pain the change removes — and source that pain from **their own
  words** (what they said in the meeting / ticket / thread), not your paraphrase of it. "You
  stop paging on-call for the 2am OOM restarts" beats "improved reliability."
- **Stay direct; cut over-caveating.** Keep only the caveats that would actually *change the
  recommendation* if the reader knew them. Delete defensive hedging that just protects you —
  it dilutes the signal and makes the doc read as unsure.
- **No parallel-customer references in outbound docs.** Never name or allude to another
  customer ("like we did for Acme…") in a document that goes to a customer. Keep comparisons,
  benchmarks, and lessons-learned generic. Cross-customer context stays internal-only.
- **Cover images: no text by default.** If a doc gets a cover/hero image, generate it
  **without embedded text** unless the human explicitly asks for a title on the image — baked-in
  text dates badly, can't be edited, and often clashes with the doc's own heading.

## Render gotchas — google-docs MCP

- **Check formatting with `gdocs_lint`, never by reading the doc back** (#2001). After any
  Docs write, call `gdocs_lint(doc_id, tab_id)` (shell: `rpw-mcp-cli call google-docs gdocs_lint --json '{"doc_id":"DOC","tab_id":"T"}'`).
  It compares every paragraph and run to `house_style.json` in code and returns
  `{ok, errors, warnings, by_rule, violations}` with no doc content. Report that result.
  Do not re-read the tab to check spacing, fonts or bullets. Warnings (non-dash bullets,
  which the API cannot create) never set `ok` to false.
- **`house_style.json` is the one source of style values.** They come from the owner's
  Jam Session template: Arial 13pt body at 1.15 line spacing, H1/H2/H3 at 22/18/16pt bold,
  `-` bullets on a 36pt indent ladder.
- **Write tools enforce the style.** `gdocs_create`, `gdocs_update`, `gdocs_add_tab` and
  `gdocs_write_to_tab` normalize the tab they wrote, then lint it. Their result carries a
  `style` summary. A status ending in `_but_style_check_failed` is an error: report it, and
  do not hand the doc over as done. Run `gdocs_lint` yourself only after other writes.

Per-construct renderer behaviour (tables, links, bullets, tabs, find/replace):
[references/render-gotchas.md](references/render-gotchas.md).

## Quick checklist before you ship a doc

- [ ] Real H2/H3 headings; no bolded-line fake headings
- [ ] Every bullet leads with a **bold** scan-target; sub-points nested, not flattened
- [ ] Identifiers in `inline code`; links as markdown
- [ ] Only functional section-tag emojis — zero cheerleader emojis
- [ ] Concrete nouns, not jargon; optional asks labeled `Optional`
- [ ] Root tab is a self-contained summary; detail pushed to subtabs
- [ ] Pain framed in the customer's own words; over-caveating cut
- [ ] No parallel-customer references anywhere in an outbound doc
- [ ] Cover image (if any) has no baked-in text
- [ ] `gdocs_lint` returns `ok: true` for every tab you wrote (formatting is checked in code, not by re-reading)
- [ ] All tabs consistent — re-open siblings and confirm they match this format
