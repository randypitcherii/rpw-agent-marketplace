---
name: morning-prep-report
description: Use when producing or reviewing the dated morning prep / day prep HTML brief — "prepare me for my day", "weekday morning prep", "morning brief", or comparing today's signals with prior preps. Supplies a branded standalone template with an inline project favicon, copyable approve/modify prompts, and an honest day-over-day chart. NOT for acting on the recommendations or for calendar/inbox writes.
---

# Morning Prep Report

Produce a skimmable, read-only daily brief that says what matters today and hands back approval-ready next steps. This is a presentation/evidence contract, not permission to act.

This published-plugin copy mirrors the Omnigent project skill in `projects/omnigent/skills/morning-prep-report/assets/SKILL.md`; tests require instructions and HTML assets to stay aligned. Detailed contract: [`references/report-contract.md`](references/report-contract.md).

## Source access gate

Before drafting, verify source access; missing native tools do not mean missing access.
- If native service tools are absent, load `mcp-cli`; use `rpw mcp` (or its bundled launcher) and follow `servers → tools → call`. Never guess schemas or bypass MCP with upstream APIs.
- For Calendar, Gmail, Slack, and task sources, make a bounded read-only content request (90 seconds per call). Gather actual day context, not just auth status. Treat auth-only success as unverified content access; prior reports are not current access evidence.
- Check each source independently; continue gathering from working sources when another fails. Do not defer available gathering to approval prompts.
- Include a compact **Source access evidence** table: source, tool/command, timestamp, window, and result (read succeeded, failed with exact error, not installed, or not attempted with reason). Missing data is not zero.
- Do not install, reauthenticate, change scopes, modify sources, or mark messages read. Report required recovery as a proposal only.

## Procedure

1. Gather with read-only operations only. Record each source, the window, timezone, and what was unavailable.
2. Copy [`assets/template.html`](assets/template.html) to `prep-YYYY-MM-DD.html`; use [`assets/example-report.html`](assets/example-report.html) as the visual reference (all its data is fictional). Never copy a prior dated report as the template, and never edit prior reports.
3. Keep the identity header: **Morning Prep** eyebrow with the full date, the inline project favicon/mark, and a one-sentence bottom line. Tab `<title>` is `YYYY-MM-DD · 🌞 Weekday Morning Prep` — date first so tabs and history sort, then the schedule name.
4. Fill the standard sections in order: today at a glance, priority map, suggested next actions, what changed since the last prep, confidence & limits.
5. Each next action gets a priority, evidence, an editable prompt in a `<textarea>`, and a copy button. Prompts propose; nothing runs without approval.
6. Compare with prior preps only for signals counted the same way. Put every count on one zero-based scale, show missing days as "not measured" (never zero, never interpolated), and keep the equivalent table. Fewer than three comparable preps = "preliminary".
7. Render and inspect at 1280px and 390px, then open the file for review. Use `dataviz`, `web-design` / `libs/ui/DESIGN.md`, and `favicon-standards` for their concerns.

## Assets

- `assets/template.html` — blank self-contained template (inline styles, script, favicon).
- `assets/example-report.html` — fictional filled example with chart + equivalent table.
- `assets/icon/` — project icon set built by `scripts/build_icons.py` from `assets/project-icons/morning-prep.png`.
- `scripts/inline_favicon.py` — re-embeds `assets/icon/favicon-32.png` as the data URI (`--check` verifies).
- `references/report-contract.md` — evidence, action, comparison, and identity rules.
