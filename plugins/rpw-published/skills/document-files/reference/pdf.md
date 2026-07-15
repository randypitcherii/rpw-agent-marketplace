# PDF — `pdfplumber` + `pypdf`

Extract text/tables, manipulate pages, and fill forms. Licenses: pdfplumber MIT, pypdf BSD.

```bash
uv run --with pdfplumber python <script.py>     # text + tables
uv run --with pypdf python <script.py>          # merge/split/rotate/forms
```

## Extract text + tables (bundled script)

```bash
uv run --with pdfplumber python scripts/pdf_extract.py report.pdf --tables --text
uv run --with pdfplumber python scripts/pdf_extract.py report.pdf --tables --page 3
```

Emits JSON: `{"pages": [{"page": 1, "text": "...", "tables": [[["h1","h2"],["a","b"]]]}]}`.
With neither `--text` nor `--tables`, both are included.

## Extract directly

```python
import pdfplumber
with pdfplumber.open("report.pdf") as pdf:
    page = pdf.pages[0]
    text = page.extract_text()              # str (None if no extractable text → likely scanned)
    tables = page.extract_tables()          # list[list[list[str]]]
    words = page.extract_words()            # positioned tokens, for layout-sensitive parsing
```

If `extract_text()` is empty/None the PDF is probably scanned images — needs OCR (e.g.
`ocrmypdf` or `pytesseract`), out of scope for pure extraction.

## Page ops, merge, split (`pypdf`)

```python
from pypdf import PdfReader, PdfWriter
reader = PdfReader("in.pdf")
writer = PdfWriter()
for page in reader.pages[0:3]:      # first 3 pages
    writer.add_page(page)
writer.append("appendix.pdf")       # concatenate another file
with open("out.pdf", "wb") as fh:
    writer.write(fh)
```

Metadata: `reader.metadata`. Rotate: `page.rotate(90)`. Encrypt: `writer.encrypt("pw")`.

## Forms (AcroForm) — see `forms`-style fills

```python
from pypdf import PdfReader, PdfWriter
reader = PdfReader("form.pdf")
writer = PdfWriter(clone_from=reader)
writer.update_page_form_field_values(
    writer.pages[0], {"full_name": "Jane Doe", "agree": "/Yes"}
)
with open("filled_form.pdf", "wb") as fh:
    writer.write(fh)
```

Inspect field names first: `reader.get_fields()`.

## Create a PDF from scratch (`reportlab`, BSD)

```python
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table
from reportlab.lib.styles import getSampleStyleSheet
doc = SimpleDocTemplate("out.pdf", pagesize=letter)
styles = getSampleStyleSheet()
doc.build([
    Paragraph("Quarterly Report", styles["Title"]),
    Table([["Region", "Sales"], ["East", "100"], ["West", "200"]]),
])
```

## Verify after writing

Re-extract and assert the content is present before reporting success.
