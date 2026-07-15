# DOCX — `python-docx` (+ `pandoc` for reads)

Create, read, and edit Word documents. License: python-docx MIT.

```bash
uv run --with python-docx python <script.py>
```

A `.docx` is a ZIP of XML. `python-docx` is the high-level API; for quick read-to-text,
`pandoc file.docx -t markdown` (system tool) is often fastest.

## Draft a document (bundled script)

```bash
uv run --with python-docx python scripts/docx_create.py --out memo.docx \
    --title "Quarterly Memo" --heading "Summary" \
    --paragraph "Revenue grew 12%." --paragraph "Costs held flat."
```

For richer structure pass a JSON spec on stdin:

```bash
echo '{"title":"Report","blocks":[{"heading":"Intro","level":1},{"paragraph":"Hello."},
       {"table":[["Region","Sales"],["East","100"]]}]}' \
  | uv run --with python-docx python scripts/docx_create.py --out report.docx --spec -
```

## Read

```python
import docx
d = docx.Document("memo.docx")
for p in d.paragraphs:
    print(p.style.name, "|", p.text)
for table in d.tables:
    for row in table.rows:
        print([c.text for c in row.cells])
```

Or shell out for a fast text dump: `pandoc memo.docx -t plain`.

## Create / edit

```python
import docx
from docx.shared import Pt, Inches
d = docx.Document()                       # or docx.Document("existing.docx") to edit
d.add_heading("Title", level=0)
d.add_heading("Section", level=1)
p = d.add_paragraph("Normal text, then ")
p.add_run("bold").bold = True             # runs carry inline formatting
d.add_paragraph("Bullet item", style="List Bullet")
table = d.add_table(rows=1, cols=2)
table.style = "Table Grid"
table.rows[0].cells[0].text = "Region"
table.add_row().cells[0].text = "East"
d.add_picture("chart.png", width=Inches(5))
d.add_page_break()
d.save("out.docx")
```

## Common extras

- **Styles**: `d.styles["Normal"].font.size = Pt(11)`; named paragraph styles via `style=`.
- **Find/replace**: iterate `paragraph.runs` and rewrite `run.text` (replacing on the paragraph
  text directly loses formatting; runs preserve it).
- **Headers/footers**: `section.header.paragraphs[0].text = "..."` per `d.sections`.
- **Tracked changes / comments**: not supported by python-docx — unpack the ZIP and edit
  `word/document.xml` directly for those.

## Verify after writing

Re-open with `docx.Document(path)` and assert your headings/paragraphs are present.
