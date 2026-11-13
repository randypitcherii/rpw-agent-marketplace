---
name: agentic-improvements-report
description: Use when producing or reviewing recurring agentic-usage improvement reports — "agentic improvements report", "review recent agent usage", or comparing usage patterns across cycles. Defines an evidence-first recommendation template and honest trend visualizations. NOT for implementing recommendations or comprehensive product analytics.
---

# Agentic Improvements Report

Produce an evidence-linked report on how agentic-tool usage is changing and which workflow improvements merit approval. This is a presentation/analysis contract, not an implementation mandate or telemetry system.

This published-plugin copy mirrors the Omnigent project skill in `projects/omnigent/skills/agentic-improvements-report/assets/SKILL.md`; tests require instructions and HTML assets to stay aligned. The repo catalog makes it discoverable. Detailed contract: [`references/reporting-contract.md`](references/reporting-contract.md).

## Procedure

1. Follow the contract's read-only evidence and sample-scope guardrails.
2. Create the report from [`assets/template.html`](assets/template.html); use [`assets/example-report.html`](assets/example-report.html) as a visual example (all its data is fictional).
3. Keep the header unmistakably branded **Agentic Improvements**, with the reporting window and bottom line. Tab `<title>` is `YYYY-MM-DD · 📊 Twice-Weekly Agentic Improvements Report` (report date, then schedule name); keep the inline project favicon.
4. Include standard approval-ready fields: priority, recommendation, evidence, impact, confidence, effort, a verification/next step, and approval/status.
5. Compare cycles only when definitions and data are comparable. Include labels, denominators, windows, source, caveats, and an equivalent table for every visualization.
6. Render and inspect at narrow width and zoom. Use `dataviz`, `web-design` / `libs/ui/DESIGN.md`, and `favicon-standards` for their respective concerns.
7. No recommendations are acted on unless explicitly approved. This skill does not define durable storage or telemetry (see #1599).

## Assets

- `assets/template.html` — blank self-contained HTML report template.
- `assets/example-report.html` — fictional cycle comparison and equivalent table.
- `assets/icon/` — project icon set built by `scripts/build_icons.py` from `assets/project-icons/agentic-improvements.png`.
- `scripts/inline_favicon.py` — re-embeds `assets/icon/favicon-32.png` as the data URI (`--check` verifies).
- `references/reporting-contract.md` — detailed evidence, recommendation, comparison, visualization, and continuity rules.
