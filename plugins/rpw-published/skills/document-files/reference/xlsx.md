# XLSX — `openpyxl`

Read, fill, and create `.xlsx` workbooks. License: MIT.

```bash
uv run --with openpyxl python <script.py>
```

## Fill cells (bundled script)

```bash
uv run --with openpyxl python scripts/xlsx_fill.py template.xlsx \
    --set "Sheet1!B2=Acme Corp" --set "Sheet1!B3=2026-06-14" --set C5=42 \
    --out filled.xlsx
```

Cell refs are `[Sheet!]CELL`; no sheet prefix → active sheet. Numeric-looking values are
written as numbers (so `=SUM(...)` works), everything else as text. Omit `--out` to edit
in place.

## Read

```python
import openpyxl
wb = openpyxl.load_workbook("book.xlsx", data_only=True)  # data_only → last-computed values
ws = wb["Sheet1"]                                          # or wb.active
print(ws["B2"].value)
for row in ws.iter_rows(min_row=1, values_only=True):      # whole-sheet sweep
    print(row)
print(ws.max_row, ws.max_column)
```

`data_only=True` returns cached formula results (only present if the file was last saved by a
real spreadsheet app); without it you get the formula string.

## Create

```python
import openpyxl
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Q2"
ws.append(["Region", "Sales"])      # header row
ws.append(["East", 100])
ws.append(["West", 200])
ws["B4"] = "=SUM(B2:B3)"            # formulas are just strings
wb.create_sheet("Notes")            # add another sheet
wb.save("report.xlsx")
```

## Common extras

- **Styling**: `from openpyxl.styles import Font, PatternFill; ws["A1"].font = Font(bold=True)`.
- **Column width**: `ws.column_dimensions["A"].width = 24`.
- **Number format**: `ws["B2"].number_format = "#,##0.00"` or `"0.0%"`.
- **Charts**: `openpyxl.chart` (BarChart/LineChart) — add data refs, then `ws.add_chart(chart, "E2")`.
- **Big files**: `load_workbook(path, read_only=True)` / `Workbook(write_only=True)` stream rows.

## Verify after writing

Re-open and print the cells you set — never report success without reading back:

```python
import openpyxl
ws = openpyxl.load_workbook("filled.xlsx").active
assert ws["B2"].value == "Acme Corp"
```
