#!/usr/bin/env python
"""Extract text and/or tables from a PDF as JSON.

Run with pdfplumber available, e.g.:
    uv run --with pdfplumber python pdf_extract.py report.pdf --tables --text

Output is a JSON object: {"pages": [{"page": 1, "text": "...", "tables": [[[...]]]}]}.
With neither --text nor --tables, both are included. --page N limits to one page (1-based).
"""
from __future__ import annotations

import argparse
import json
import sys

import pdfplumber


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Extract text/tables from a PDF as JSON.")
    ap.add_argument("pdf", help="path to the .pdf file")
    ap.add_argument("--text", action="store_true", help="include page text")
    ap.add_argument("--tables", action="store_true", help="include detected tables")
    ap.add_argument("--page", type=int, help="limit to one 1-based page number")
    args = ap.parse_args(argv)

    # Default to everything when the caller specifies no projection.
    want_text = args.text or not (args.text or args.tables)
    want_tables = args.tables or not (args.text or args.tables)

    pages_out = []
    with pdfplumber.open(args.pdf) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            if args.page and idx != args.page:
                continue
            entry = {"page": idx}
            if want_text:
                entry["text"] = page.extract_text() or ""
            if want_tables:
                # Default (line-ruled) detection first; fall back to the text
                # strategy so borderless tables are still extracted.
                tables = page.extract_tables() or []
                if not tables:
                    tables = page.extract_tables(
                        {"vertical_strategy": "text", "horizontal_strategy": "text"}
                    ) or []
                entry["tables"] = tables
            pages_out.append(entry)

    json.dump({"pages": pages_out}, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
