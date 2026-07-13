---
name: doc-styling
description: Formatting and voice rules for authoring or editing Google Docs and customer-facing prose. Trigger on "write this up as a customer doc", "draft a gdoc", "format this doc", "email-style formatting", or editing any Google Doc tab or outbound customer write-up. Encodes email/technical-note structure (real headings, dashed bullets, bold scan-targets, inline code, functional emojis), customer-doc voice, pain-avoided framing, and render gotchas. NOT for plain code docs, READMEs, or code comments.
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

**NOT for:** plain code documentation, READMEs, API reference, inline code comments, or
commit/PR bodies. Those have their own conventions; don't impose email-style section tags on them.

## Format — email / technical-note style

Write for scanning, the way a well-structured internal email or technical note reads.

- **Real headings, not bold paragraphs.** Use actual H2 / H3 heading levels (`##`, `###`)
  so the doc has a navigable structure — never fake a heading by bolding a normal line.
- **One blank line between sections.** Give the reader breathing room; don't wall-of-text.
- **Dashed bullets** (`-`) for lists. Keep each bullet to one idea.
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

Verified against the current `plugins/rpw-published/mcp-servers/google-docs/` source. Behavior
has shifted as bugs were fixed — trust the code, and when a live doc matters, validate the
render (create a scratch doc, write test content, read it back or eyeball it, then delete it).

- **Markdown tables in nested sub-tabs write correctly** (was #198, fixed). The historical
  bug — tables rendering as empty grids in sub-tabs — came from a flat `tabId` scan that missed
  nested tabs; `write_to_tab` now resolves tabs through the recursive `_find_tab_by_id`, so
  tables land with content at any nesting depth. Tables are safe; you don't need to fall back
  to bulleted rows to work around this.
- **Hyperlinks, inline-cell formatting, and nested link-bullets render correctly** (#222,
  verified fixed). Code hyperlinks (`` [`code`](url) ``) get color-only styling (the auto
  underline is cleared so it doesn't clash with underscores); codespans inside **bold** are
  emitted at `weight:700` so they stay bold *and* monospace.
- **Bullet inheritance + paragraph spacing are fixed** (#301). Inherited list bullets are
  cleared and paragraph spacing is normalized, so re-writing a tab no longer leaves stray
  bullets or compressed/expanded spacing from prior content.
- **`gdocs_read` reads nested sub-tabs and their tables** (#216). The current read path
  recurses into `childTabs` at any depth and renders each table's cells as tab-separated text,
  so sub-tab table content *is* surfaced. Doc-read API shape has bitten before (per-tab vs.
  top-level nesting), so for a high-stakes render still confirm against the live doc rather than
  trusting a single read.
- **`gdocs_find_replace` supports tab scoping.** Passing `tab_id` now sends the API-correct
  `tabsCriteria.tabIds`, so a tab-scoped replace works — the old Docs-API 400 came from an
  unsupported request shape and no longer applies. A unique `find_text` still works doc-wide
  when you omit `tab_id`; prefer that when the target string is already unique.

## Quick checklist before you ship a doc

- [ ] Real H2/H3 headings; no bolded-line fake headings
- [ ] Every bullet leads with a **bold** scan-target
- [ ] Identifiers in `inline code`; links as markdown
- [ ] Only functional section-tag emojis — zero cheerleader emojis
- [ ] Concrete nouns, not jargon; optional asks labeled `Optional`
- [ ] Root tab is a self-contained summary; detail pushed to subtabs
- [ ] Pain framed in the customer's own words; over-caveating cut
- [ ] No parallel-customer references anywhere in an outbound doc
- [ ] Cover image (if any) has no baked-in text
- [ ] All tabs consistent — re-open siblings and confirm they match this format
