"""
Block-level markdown → Docs batchUpdate renderer.

``_insert_markdown`` parses markdown (mistune AST) and emits Google Docs
``batchUpdate`` requests for headings, paragraphs, lists, blockquotes, code
blocks, horizontal rules, inline images, and real tables. It is the shared
insertion path behind ``create_doc``, ``update_doc``, ``add_tab``, and
``write_to_tab``.

Network calls go through ``auth.api`` (module-qualified so tests patch a single
point); tab-body lookups use the recursive ``tabs._find_tab_by_id``.
"""

from typing import Any, Dict, List, Optional

import auth
import tabs
from config import DEFAULT_CODE_FONT, PARAGRAPH_SPACE_BELOW_PT
from markdown_inline import (
    _children_contain_image,
    _image_url,
    _is_image_token,
    _mk_location,
    _mk_range,
    _plain_text_from_children,
    _utf16_len,
    _walk_inlines,
)


def _insert_markdown(doc_id: str, content: str, index: int = 1, tab_id: Optional[str] = None,
                     code_font: str = DEFAULT_CODE_FONT, bullet_preset: str = ""):
    """Insert markdown content into a doc at the given index, with full formatting.

    Uses mistune>=3.0.0 to parse markdown into an AST, then walks the AST
    to emit Google Docs batchUpdate requests.

    Supported constructs:
      - ATX headings (#–######)
      - Paragraphs with **bold**, *italic*, `inline code`, [text](url)
      - Unordered lists (- item, * item) — createParagraphBullets BULLET_DISC_CIRCLE_SQUARE
      - Ordered lists (1. item) — createParagraphBullets NUMBERED_DECIMAL_ALPHA_ROMAN
      - Fenced code blocks (```) — code_font font (default: Courier New)
      - Blockquotes (> text) — rendered as italic paragraph (Docs has no native blockquote)
      - Horizontal rules (---) — rendered as a line of ─ characters
      - Tables — real Docs tables via two-phase insertTable + cell insertText (reverse order)

    Args:
        code_font: Font family for code blocks and inline code. Defaults to "Courier New".
        bullet_preset: Docs API bulletPreset for unordered lists (#170). Empty string =
            BULLET_DISC_CIRCLE_SQUARE (today's default). Validated by callers (write_to_tab).
    """
    import mistune

    md = mistune.create_markdown(renderer="ast", plugins=["table"])
    tokens = md(content)

    requests: List[Dict] = []
    current_index = index

    def _body_content_from_doc(resp: Dict) -> List[Dict]:
        if tab_id:
            tab = tabs._find_tab_by_id(resp.get("tabs", []), tab_id)
            return tab.get("documentTab", {}).get("body", {}).get("content", []) if tab else []
        return resp.get("body", {}).get("content", [])

    def _live_append_index(fallback: int) -> int:
        """Clamp a tab append to the live valid insertion point.

        Docs tab bodies reject structural inserts at the segment end index itself:
        appending must target the trailing paragraph boundary (endIndex - 1). After
        flushing a batch, our virtual current_index can equal the segment end, so
        re-read the tab and clamp before inserting tables/images.
        """
        if not tab_id:
            return fallback
        doc = auth.api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true")
        body_content = _body_content_from_doc(doc)
        if not body_content:
            return fallback
        end_index = body_content[-1].get("endIndex")
        if not isinstance(end_index, int):
            return fallback
        return min(fallback, max(index, end_index - 1))

    def sync_to_live_append_index() -> None:
        """Refresh current_index only when prior requests are already flushed."""
        nonlocal current_index
        if tab_id and current_index > index and not requests:
            current_index = _live_append_index(current_index)

    def flush_requests() -> bool:
        nonlocal requests
        if not requests:
            return False
        for i in range(0, len(requests), 50):
            batch = requests[i:i + 50]
            auth.api(
                "POST",
                f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
                {"requests": batch},
            )
        requests = []
        return True

    def paragraph_format_requests(rng: Dict, named_style: Optional[str]) -> List[Dict]:
        """Build the paragraph-level requests shared by every non-list paragraph.

        Two concerns, both #301:
          - updateParagraphStyle sets the named style AND a small spaceBelow, so
            multi-paragraph prose renders with visible gaps instead of a smashed
            wall (bug 2). Blank markdown lines are dropped, so this is the only
            source of inter-paragraph spacing.
          - deleteParagraphBullets clears any list bullet the paragraph inherited
            from the tab's anchor paragraph (bug 1). Splitting a still-bulleted
            anchor paragraph makes every inserted paragraph inherit its bullet;
            this is a no-op when there is no bullet. It is the mirror of the #171
            list-branch NORMAL_TEXT reset (headings/paragraphs inheriting a bullet
            vs. list items inheriting a heading style).
        """
        paragraph_style: Dict[str, Any] = {"spaceBelow": {"magnitude": PARAGRAPH_SPACE_BELOW_PT, "unit": "PT"}}
        fields = ["spaceBelow"]
        if named_style:
            paragraph_style["namedStyleType"] = named_style
            fields.insert(0, "namedStyleType")
        return [
            {
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": paragraph_style,
                    "fields": ",".join(fields),
                }
            },
            {"deleteParagraphBullets": {"range": rng}},
        ]

    def emit_text_paragraph(text: str, inline_requests: List[Dict],
                            named_style: Optional[str] = None) -> int:
        """Emit insertText + paragraph style + bullet-clear + inline style requests.
        Returns the new current_index."""
        nonlocal requests
        sync_to_live_append_index()
        insert_text = text + "\n"
        location = _mk_location(current_index, tab_id)
        requests.append({"insertText": {"location": location, "text": insert_text}})
        end_idx = current_index + _utf16_len(insert_text)

        rng = _mk_range(current_index, end_idx, tab_id)
        requests.extend(paragraph_format_requests(rng, named_style))

        requests.extend(inline_requests)
        return end_idx

    def emit_rich_paragraph(children: List[Dict[str, Any]], named_style: Optional[str] = None) -> int:
        """Emit a paragraph that may contain inline images.

        Docs inline images occupy one document index. Text around the image is inserted as
        normal text, while markdown image tokens map to insertInlineImage requests.
        """
        nonlocal requests, current_index
        sync_to_live_append_index()
        paragraph_start = current_index
        inline_requests: List[Dict] = []
        segment: List[Dict[str, Any]] = []

        def flush_segment() -> None:
            nonlocal current_index, segment
            if not segment:
                return
            text = _plain_text_from_children(segment)
            if text:
                segment_start = current_index
                requests.append({
                    "insertText": {
                        "location": _mk_location(segment_start, tab_id),
                        "text": text,
                    }
                })
                inline_requests.extend(
                    _walk_inlines(segment, segment_start, tab_id, code_font=code_font)
                )
                current_index += _utf16_len(text)
            segment = []

        for child in children:
            if _is_image_token(child):
                flush_segment()
                requests.append({
                    "insertInlineImage": {
                        "location": _mk_location(current_index, tab_id),
                        "uri": _image_url(child),
                    }
                })
                current_index += 1
            else:
                segment.append(child)
        flush_segment()

        requests.append({
            "insertText": {
                "location": _mk_location(current_index, tab_id),
                "text": "\n",
            }
        })
        current_index += 1
        rng = _mk_range(paragraph_start, current_index, tab_id)
        requests.extend(paragraph_format_requests(rng, named_style))
        requests.extend(inline_requests)
        return current_index

    def list_item_inline_children(item: Dict[str, Any]) -> List[Dict[str, Any]]:
        for child in item.get("children", []):
            if child.get("type") in ("block_text", "paragraph"):
                return child.get("children", [])
        return []

    def emit_list_lines(list_token: Dict[str, Any], depth: int = 0) -> None:
        """Insert all list item lines, preserving nested items with leading tabs."""
        nonlocal current_index, requests
        sync_to_live_append_index()
        prefix = "\t" * depth
        prefix_len = _utf16_len(prefix)
        for item in list_token.get("children", []):
            children = list_item_inline_children(item)
            text = _plain_text_from_children(children)
            if text:
                insert_text = prefix + text + "\n"
                item_start = current_index
                requests.append({
                    "insertText": {
                        "location": _mk_location(item_start, tab_id),
                        "text": insert_text,
                    }
                })
                requests.extend(
                    _walk_inlines(
                        children,
                        item_start + prefix_len,
                        tab_id,
                        code_font=code_font,
                    )
                )
                current_index += _utf16_len(insert_text)
            for child in item.get("children", []):
                if child.get("type") == "list":
                    emit_list_lines(child, depth + 1)

    for token in tokens:
        t = token.get("type", "")

        if t == "blank_line":
            continue

        elif t == "heading":
            level = token["attrs"]["level"]
            children = token.get("children", [])
            if _children_contain_image(children):
                current_index = emit_rich_paragraph(children, f"HEADING_{level}")
            else:
                text = _plain_text_from_children(children)
                inline_reqs = _walk_inlines(children, current_index, tab_id, code_font=code_font)
                current_index = emit_text_paragraph(text, inline_reqs, f"HEADING_{level}")

        elif t == "paragraph":
            children = token.get("children", [])
            if _children_contain_image(children):
                current_index = emit_rich_paragraph(children, "NORMAL_TEXT")
            else:
                text = _plain_text_from_children(children)
                inline_reqs = _walk_inlines(children, current_index, tab_id, code_font=code_font)
                current_index = emit_text_paragraph(text, inline_reqs, "NORMAL_TEXT")

        elif t == "block_quote":
            # Render as italic paragraph — Docs has no native blockquote type
            for child in token.get("children", []):
                if child.get("type") == "paragraph":
                    text = _plain_text_from_children(child.get("children", []))
                    insert_text = text + "\n"
                    location = _mk_location(current_index, tab_id)
                    requests.append({"insertText": {"location": location, "text": insert_text}})
                    end_idx = current_index + _utf16_len(insert_text)
                    rng = _mk_range(current_index, end_idx, tab_id)
                    requests.append({
                        "updateTextStyle": {
                            "range": rng,
                            "textStyle": {"italic": True},
                            "fields": "italic",
                        }
                    })
                    current_index = end_idx

        elif t == "block_code":
            # Fenced or indented code block — insert raw text with code_font
            code_text = token.get("raw", "").rstrip("\n")
            insert_text = code_text + "\n"
            location = _mk_location(current_index, tab_id)
            requests.append({"insertText": {"location": location, "text": insert_text}})
            end_idx = current_index + _utf16_len(insert_text)
            rng = _mk_range(current_index, end_idx, tab_id)
            requests.append({
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": {"weightedFontFamily": {"fontFamily": code_font}},
                    "fields": "weightedFontFamily",
                }
            })
            current_index = end_idx

        elif t == "thematic_break":
            # Render as a line of Unicode box-drawing horizontal chars
            hr_text = "─" * 40
            insert_text = hr_text + "\n"
            location = _mk_location(current_index, tab_id)
            requests.append({"insertText": {"location": location, "text": insert_text}})
            current_index += _utf16_len(insert_text)

        elif t == "list":
            ordered = token.get("attrs", {}).get("ordered", False)
            # Ordered lists always use the numbered preset. Unordered lists honor
            # the caller's bullet_preset override (#170), defaulting to the disc.
            if ordered:
                preset = "NUMBERED_DECIMAL_ALPHA_ROMAN"
            else:
                preset = bullet_preset or "BULLET_DISC_CIRCLE_SQUARE"
            list_start = current_index

            # Insert all list item lines first, then add bullets in one request. Nested
            # list items use leading tabs, which Docs consumes as bullet nesting levels.
            emit_list_lines(token)

            list_end = current_index
            rng = _mk_range(list_start, list_end, tab_id)
            requests.append({
                "createParagraphBullets": {
                    "range": rng,
                    "bulletPreset": preset,
                }
            })
            # #171: explicitly reset list paragraphs to NORMAL_TEXT. Otherwise,
            # when the cursor follows a HEADING_N paragraph, the inserted list
            # items inherit that heading style — createParagraphBullets only
            # changes the bullet glyph, not namedStyleType. The "namedStyleType"
            # field mask means this does NOT strip the bullets we just applied.
            requests.append({
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "namedStyleType",
                }
            })

        elif t == "table":
            # Two-phase real Docs table insertion.
            # Phase 1: Flush pending requests, then emit insertTable.
            # Phase 2: Discover cell indices via documents.get, then insert cell
            #          text in reverse order so prior indices stay valid.
            #
            # Collect all row/cell (text, children) pairs from the AST.
            # children are preserved so _walk_inlines can emit inline styling later.
            all_rows: List[List[tuple]] = []  # rows of (cell_text, cell_children)
            num_cols = 0
            for child in token.get("children", []):
                ct = child.get("type", "")
                if ct == "table_head":
                    cells = child.get("children", [])
                    num_cols = len(cells)
                    all_rows.append([
                        (_plain_text_from_children(c.get("children", [])), c.get("children", []))
                        for c in cells
                    ])
                elif ct == "table_body":
                    for row in child.get("children", []):
                        cells = row.get("children", [])
                        all_rows.append([
                            (_plain_text_from_children(c.get("children", [])), c.get("children", []))
                            for c in cells
                        ])

            num_rows = len(all_rows)
            if num_rows == 0 or num_cols == 0:
                continue  # empty table token — skip

            # Flush any pending requests before table insertion.
            if flush_requests():
                sync_to_live_append_index()

            # Phase 1: Insert the table structure. Remember where we asked the
            # API to put it — Phase 2 uses this to pick the right element when
            # the doc body has more than one table.
            table_insert_index = current_index
            table_location = _mk_location(table_insert_index, tab_id)
            auth.api(
                "POST",
                f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
                {
                    "requests": [
                        {
                            "insertTable": {
                                "rows": num_rows,
                                "columns": num_cols,
                                "location": table_location,
                            }
                        }
                    ]
                },
            )

            # Phase 2: Discover cell start indices from the live document.
            get_url = f"https://docs.googleapis.com/v1/documents/{doc_id}"
            if tab_id:
                get_url += "?includeTabsContent=true"
            doc_resp = auth.api("GET", get_url)

            # Find the table element in the document body (or tab body if tab_id).
            # Route the tab lookup through the recursive walker so nested sub-tabs
            # (under childTabs) are found — a flat scan of top-level `tabs` returns
            # [] for any depth>=1 tab, leaving the just-inserted grid empty (#198).
            body_content = _body_content_from_doc(doc_resp)

            # Pick the table we just inserted: smallest startIndex at or after
            # where we asked the API to place it. Without this, a pre-existing
            # table at a lower index would absorb our cell inserts.
            candidates = [
                e for e in body_content
                if "table" in e and e.get("startIndex", -1) >= table_insert_index
            ]
            matched_elem = min(candidates, key=lambda e: e["startIndex"], default=None)
            if matched_elem is None:
                # No table found at/after insertion point — fall back to first table.
                matched_elem = next((e for e in body_content if "table" in e), None)
            if matched_elem is None:
                continue  # Can't discover indices; skip cell fill.

            table_element = matched_elem["table"]

            # Extract (row_idx, col_idx, cell_start_index, text, children) for all cells.
            cell_data: List[tuple] = []  # (row_idx, col_idx, start_index, text, children)
            table_rows = table_element.get("tableRows", [])
            for row_idx, tr in enumerate(table_rows):
                for col_idx, tc in enumerate(tr.get("tableCells", [])):
                    cell_content = tc.get("content", [])
                    if cell_content:
                        # Use the startIndex of the first paragraph in the cell
                        cell_start = cell_content[0].get("startIndex", None)
                        if cell_start is not None:
                            cell_text = ""
                            cell_children: List = []
                            if row_idx < len(all_rows) and col_idx < len(all_rows[row_idx]):
                                cell_text, cell_children = all_rows[row_idx][col_idx]
                            cell_data.append((row_idx, col_idx, cell_start, cell_text, cell_children))

            # Insert cell text in REVERSE order so earlier indices remain valid.
            # Header-row bold and inline style requests piggyback on the same
            # batch and target the just-inserted text via offset from cell_start.
            cell_data_sorted = sorted(cell_data, key=lambda x: x[2], reverse=True)
            cell_requests: List[Dict] = []
            inserted_chars = 0
            for row_idx, col_idx, cell_start, cell_text, cell_children in cell_data_sorted:
                if cell_text:
                    location = _mk_location(cell_start, tab_id)
                    cell_requests.append({"insertText": {"location": location, "text": cell_text}})
                    inserted_chars += _utf16_len(cell_text)
                    if row_idx == 0:
                        bold_range = _mk_range(cell_start, cell_start + _utf16_len(cell_text), tab_id)
                        cell_requests.append({
                            "updateTextStyle": {
                                "range": bold_range,
                                "textStyle": {"bold": True},
                                "fields": "bold",
                            }
                        })
                    # Emit inline styling (bold, italic, code, links) for formatted
                    # markdown substrings within the cell, targeting only the
                    # formatted span — NOT the whole cell.
                    inline_reqs = _walk_inlines(cell_children, cell_start, tab_id, code_font=code_font)
                    cell_requests.extend(inline_reqs)

            if cell_requests:
                for i in range(0, len(cell_requests), 50):
                    batch = cell_requests[i:i + 50]
                    auth.api(
                        "POST",
                        f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
                        {"requests": batch},
                    )

            # Advance current_index past the table. matched_elem.endIndex is
            # the table's end BEFORE cell text was inserted; cell fills pushed
            # it forward by `inserted_chars`. Without that delta, following
            # paragraphs would land inside the last cell.
            current_index = matched_elem.get("endIndex", current_index) + inserted_chars

    # Execute in batches of 50
    flush_requests()
