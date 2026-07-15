#!/usr/bin/env python
"""Fill cells in an .xlsx workbook.

Run with openpyxl available, e.g.:
    uv run --with openpyxl python xlsx_fill.py book.xlsx --set "Sheet1!B2=Hello" --set A1=Name

Cell refs are `[Sheet!]CELL`. Without a sheet prefix the active sheet is used.
Values that parse as int/float are written as numbers; everything else as text.
Writes in place unless --out is given.
"""
from __future__ import annotations

import argparse
import sys

import openpyxl


def _coerce(value: str):
    """Write numeric-looking values as numbers so formulas/sums work downstream."""
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


def _split_ref(ref: str) -> tuple[str | None, str]:
    if "!" in ref:
        sheet, cell = ref.split("!", 1)
        return sheet, cell
    return None, ref


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fill cells in an .xlsx workbook.")
    ap.add_argument("workbook", help="path to the .xlsx file")
    ap.add_argument(
        "--set",
        dest="assignments",
        action="append",
        default=[],
        metavar="[SHEET!]CELL=VALUE",
        help="cell assignment; repeatable",
    )
    ap.add_argument("--out", help="output path (default: overwrite input)")
    args = ap.parse_args(argv)

    wb = openpyxl.load_workbook(args.workbook)
    for assignment in args.assignments:
        if "=" not in assignment:
            ap.error(f"--set expects [SHEET!]CELL=VALUE, got: {assignment!r}")
        ref, value = assignment.split("=", 1)
        sheet, cell = _split_ref(ref.strip())
        ws = wb[sheet] if sheet else wb.active
        ws[cell] = _coerce(value)

    out = args.out or args.workbook
    wb.save(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
