#!/usr/bin/env python
"""Draft a .docx from simple flags or a JSON spec.

Run with python-docx available, e.g.:
    uv run --with python-docx python docx_create.py --out memo.docx \
        --title "Quarterly Memo" --heading "Summary" --paragraph "First line."

For richer documents, pass a JSON spec on stdin with --spec -:
    {"title": "...", "blocks": [{"heading": "H", "level": 2}, {"paragraph": "..."},
                                 {"table": [["a","b"],["1","2"]]}]}
Flag-built blocks are appended after any --spec blocks, in flag order.
"""
from __future__ import annotations

import argparse
import json
import sys

import docx


def _add_table(document, rows):
    if not rows:
        return
    table = document.add_table(rows=len(rows), cols=len(rows[0]))
    table.style = "Table Grid"
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            table.cell(r, c).text = str(val)


def _apply_blocks(document, blocks):
    for block in blocks:
        if "heading" in block:
            document.add_heading(block["heading"], level=int(block.get("level", 1)))
        elif "paragraph" in block:
            document.add_paragraph(block["paragraph"])
        elif "table" in block:
            _add_table(document, block["table"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Draft a .docx file.")
    ap.add_argument("--out", required=True, help="output .docx path")
    ap.add_argument("--title", help="document title (level-0 heading)")
    ap.add_argument("--spec", help="JSON spec path, or - for stdin")
    ap.add_argument("--heading", action="append", default=[], help="add a heading; repeatable")
    ap.add_argument("--paragraph", action="append", default=[], help="add a paragraph; repeatable")
    args = ap.parse_args(argv)

    document = docx.Document()
    if args.title:
        document.add_heading(args.title, level=0)

    if args.spec:
        if args.spec == "-":
            raw = sys.stdin.read()
        else:
            with open(args.spec, encoding="utf-8") as fh:
                raw = fh.read()
        spec = json.loads(raw)
        if spec.get("title") and not args.title:
            document.add_heading(spec["title"], level=0)
        _apply_blocks(document, spec.get("blocks", []))

    for heading in args.heading:
        document.add_heading(heading, level=1)
    for paragraph in args.paragraph:
        document.add_paragraph(paragraph)

    document.save(args.out)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
