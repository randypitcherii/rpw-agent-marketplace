#!/usr/bin/env python3
"""
Google Docs CLI — CRUD operations scoped to a specific Drive folder.

Uses gcloud ADC auth (same as vibe's google-tools).

Operations:
  create   - Create a new doc from markdown in the target folder
  list     - List docs in the target folder
  read     - Read a doc's content (plain text)
  update   - Append markdown content to an existing doc
  delete   - Trash a doc
  add-tab  - Add a sub-tab (named tab) to a doc

Usage:
  uv run python cli.py create --title "My Doc" --content "# Hello\n\nWorld"
  uv run python cli.py list
  uv run python cli.py read --doc-id DOC_ID
  uv run python cli.py update --doc-id DOC_ID --content "## New Section\n\nMore text"
  uv run python cli.py delete --doc-id DOC_ID
  uv run python cli.py add-tab --doc-id DOC_ID --tab-name "Notes" --content "# Notes\n\nSome notes"
"""

import argparse
import json
import sys

from docs_read import list_docs, read_doc
from docs_write import add_tab, create_doc, delete_doc, update_doc


def main():
    parser = argparse.ArgumentParser(
        description="Google Docs CLI — CRUD + tabs, scoped to a Drive folder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p = sub.add_parser("create", help="Create a new doc")
    p.add_argument("--title", "-t", required=True)
    p.add_argument("--content", "-c", default=None, help="Markdown content")
    p.add_argument("--file", "-f", default=None, help="Read content from file")

    # list
    sub.add_parser("list", help="List docs in target folder")

    # read
    p = sub.add_parser("read", help="Read a doc")
    p.add_argument("--doc-id", "-d", required=True)

    # update
    p = sub.add_parser("update", help="Append content to a doc")
    p.add_argument("--doc-id", "-d", required=True)
    p.add_argument("--content", "-c", default=None)
    p.add_argument("--file", "-f", default=None, help="Read content from file")

    # delete
    p = sub.add_parser("delete", help="Trash a doc")
    p.add_argument("--doc-id", "-d", required=True)

    # add-tab
    p = sub.add_parser("add-tab", help="Add a tab (or sub-tab) to a doc")
    p.add_argument("--doc-id", "-d", required=True)
    p.add_argument("--tab-name", "-n", required=True)
    p.add_argument("--parent-tab-id", "-p", default=None, help="Parent tab ID to nest under")
    p.add_argument("--icon", default=None, help="Emoji icon for the tab")
    p.add_argument("--content", "-c", default=None)
    p.add_argument("--file", "-f", default=None, help="Read content from file")

    args = parser.parse_args()

    try:
        if args.command == "create":
            content = args.content
            if args.file:
                with open(args.file) as f:
                    content = f.read()
            result = create_doc(args.title, content)

        elif args.command == "list":
            result = list_docs()

        elif args.command == "read":
            result = read_doc(args.doc_id)

        elif args.command == "update":
            content = args.content
            if args.file:
                with open(args.file) as f:
                    content = f.read()
            if not content:
                print("ERROR: --content or --file required", file=sys.stderr)
                sys.exit(1)
            result = update_doc(args.doc_id, content)

        elif args.command == "delete":
            result = delete_doc(args.doc_id)

        elif args.command == "add-tab":
            content = args.content
            if args.file:
                with open(args.file) as f:
                    content = f.read()
            result = add_tab(args.doc_id, args.tab_name, content,
                            parent_tab_id=args.parent_tab_id,
                            icon_emoji=args.icon)

        print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
