---
name: document-files
description: Read, create, edit, and extract from binary Office/PDF files (.pdf, .docx, .xlsx, .pptx) using open-source Python libraries. Trigger on "fill in this xlsx", "extract tables from this PDF", "draft a docx", "edit this Word doc", "build a pptx/slide deck", "read this spreadsheet", "pull text from a PDF", or any request to produce or parse an offline office document. NOT for Google-native Docs/Sheets/Slides (use the google-docs MCP) or plain-text/markdown.
---

# Document files — PDF / DOCX / XLSX / PPTX

Manipulate offline binary office documents with open-source Python libraries. This is the
offline/binary counterpart to the `google-docs` MCP (which covers Google-native docs).

## When to use

- **Fill / read / build a spreadsheet** (.xlsx) → `reference/xlsx.md`
- **Extract text or tables from, or read, a PDF** (.pdf) → `reference/pdf.md`
- **Draft / read / edit a Word document** (.docx) → `reference/docx.md`
- **Build / edit a slide deck** (.pptx) → `reference/pptx.md`

Do NOT use for Google Docs/Sheets/Slides (use the `google-docs` MCP) or for `.txt`/`.md`.

## Environment — no persistent venv

Every library here is run on demand with `uv` so nothing pollutes the project env. Pattern:

```bash
uv run --with <library> python <script-or-snippet>
```

Library per format (all MIT/BSD — see `PROVENANCE.md`):

| Format | Read / extract | Create / edit | Library |
|--------|----------------|---------------|---------|
| .xlsx  | yes | yes | `openpyxl` |
| .pdf   | yes (text + tables + forms) | (generation: `reportlab`) | `pdfplumber`, `pypdf` |
| .docx  | yes (`pandoc` or `python-docx`) | yes | `python-docx` |
| .pptx  | yes | yes | `python-pptx` |

## Bundled scripts (the common verbs)

Run from this skill's `scripts/` directory. Each is self-describing via `--help`.

```bash
# Fill cells in a workbook (acceptance: "fill in this xlsx")
uv run --with openpyxl python scripts/xlsx_fill.py book.xlsx --set "Sheet1!B2=Hello" --set A1=Name

# Extract text + tables from a PDF as JSON (acceptance: "extract tables from this PDF")
uv run --with pdfplumber python scripts/pdf_extract.py report.pdf --tables --text

# Draft a Word document (acceptance: "draft a docx")
uv run --with python-docx python scripts/docx_create.py --out memo.docx \
    --title "Quarterly Memo" --heading "Summary" --paragraph "First line."
```

For anything beyond these verbs — editing existing files, forms, styling, charts, slides —
open the matching `reference/<format>.md` and follow the library recipes there. The reference
files are the detailed instructions; this SKILL.md is the router.

## How to work

1. Identify the file format from the extension or the user's words.
2. For the three common verbs above, run the bundled script directly.
3. Otherwise, load the relevant `reference/<format>.md` and write a short `uv run --with …`
   snippet or script using the recipes there.
4. Verify the result by reading the file back (e.g. re-open the workbook and print the cell;
   re-parse the PDF) before reporting success — never assert a write worked without reading it.

## Provenance

This skill was written in-house on open-source libraries rather than adopting Anthropic's
first-party document skills, which ship under a proprietary license that forbids copying,
derivative works, distribution, and use outside Anthropic's own services. See `PROVENANCE.md`
for the full decision and the license of every dependency.
