# Provenance — `document-files` skill

## Decision: written in-house, NOT adopted from `anthropics/skills`

Issue #263 asked us to evaluate adopting Anthropic's first-party document skills
(`anthropics/skills`: `pdf`, `docx`, `xlsx`, `pptx`) versus writing our own. We **wrote our
own**. The deciding factor is licensing, verified directly against the source repo on
2026-06-14.

### What the Anthropic skills are licensed under

Each skill in `anthropics/skills` ships its own `LICENSE.txt`:

> © 2025 Anthropic, PBC. All rights reserved.
> … users may not:
> - Extract these materials from the Services or retain copies of these materials outside the Services
> - Reproduce or copy these materials …
> - Create derivative works based on these materials
> - Distribute, sublicense, or transfer these materials to any third party
> … Reverse engineer, decompile, or disassemble these materials

There is **no permissive root license** on the repo. `THIRD_PARTY_NOTICES.md` only covers the
OSS libraries bundled *inside* those skills (imageio, etc.), not the skill content itself.

### How each option scored

| Option | Verdict | Why |
|--------|---------|-----|
| **1. Vendor/adopt into this marketplace** | ✗ Prohibited | Copying + derivative works + distribution into our (public-bound) marketplace each violate the license outright. |
| **2. Install-don't-vendor** (`npx skills add anthropics/skills`) | ✗ Breaches license for our use | The license forbids retaining copies / use *outside Anthropic's Services*. Acceptance #263 requires the skill to work in **a non-Claude harness** (Cursor/Codex/DeepAgents) — i.e. outside the Services. Also makes the library depend on opaque external content we can't de-personalize or pin. |
| **3. Write our own on permissive OSS** | ✓ Chosen | The only legally clean path that satisfies cross-harness acceptance, records clean provenance, and composes with ADR-2026-06-12 distribution. |

The issue's framing ("writing our own is almost certainly wrong — don't reinvent the
most-shipped skills") assumed the Anthropic skills were source-available and vendorable. The
actual proprietary license inverts that: we cannot legally copy or build derivatives, and our
cross-harness requirement rules out the install path too. File-format techniques (unzip a
`.docx`, read its XML, call `openpyxl`) are uncopyrightable facts and standard library usage —
authoring our own instructions over those libraries is independent work, not a derivative of
Anthropic's prose or code.

## Dependencies and their licenses

All runtime dependencies are permissively licensed (MIT or BSD) and pulled on demand via
`uv run --with …` — none are vendored into this repo.

| Library | Purpose | License |
|---------|---------|---------|
| `openpyxl` | read/write `.xlsx` | MIT |
| `pdfplumber` | extract text/tables from `.pdf` | MIT |
| `pypdf` | merge/split/forms on `.pdf` | BSD-3-Clause |
| `python-docx` | read/write `.docx` | MIT |
| `python-pptx` | read/write `.pptx` | MIT |
| `reportlab` (optional) | generate `.pdf` from scratch | BSD-3-Clause |
| `pandoc` (optional, system tool) | convert `.docx` ↔ markdown | GPL-2.0+ (invoked as an external tool, not linked/vendored) |

## Authorship

All `SKILL.md`, `reference/*.md`, and `scripts/*.py` content in this skill was written
independently for this repository. No content was copied from `anthropics/skills`.
