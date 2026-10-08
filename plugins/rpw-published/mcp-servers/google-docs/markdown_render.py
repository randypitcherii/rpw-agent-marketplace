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

from typing import Any, Dict, List, Optional, Tuple

import auth
import tabs
import config
from config import CODE_FONT, LIST_INDENT_PER_LEVEL_PT
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


def _insert_markdown(doc_id: str, content: str, index: int = 1,
                     tab_id: Optional[str] = None) -> Dict:
    """Insert markdown content into a doc at the given index, with full formatting.

    Uses mistune>=3.0.0 to parse markdown into an AST, then walks the AST
    to emit Google Docs batchUpdate requests.

    Returns a result envelope (#423 — errors are no longer swallowed):
      - success: ``{"status": "inserted", "batchesSent": N, "requestsSent": M}``
      - failure: ``{"status": "insert_failed", "error": <message>,
        "apiError": <google error>, "batchesCompleted": N}`` — batchesCompleted
        counts batchUpdate calls that succeeded before the failure, so callers
        can distinguish a partial write (truncation) from a total failure.
    Every batchUpdate response is checked for a Google error envelope; any
    429/400/500/quota error aborts the insert instead of silently continuing.

    Supported constructs: see ``_insert_markdown_raising``.

    Rendering has no knobs and emits structure only. Paragraph spacing, fonts
    and sizes come from the named styles, which the house-style normalize pass
    pins after every write tool (#2001; house_style.json, style_normalize.py).
    """
    stats = {"batches": 0, "requests": 0}
    try:
        _insert_markdown_raising(doc_id, content, index, tab_id, stats)
    except auth.DocsApiError as e:
        return {
            "status": "insert_failed",
            "error": str(e),
            "apiError": e.envelope.get("error"),
            "batchesCompleted": stats["batches"],
        }
    return {
        "status": "inserted",
        "batchesSent": stats["batches"],
        "requestsSent": stats["requests"],
    }


def _insert_markdown_raising(doc_id: str, content: str, index: int, tab_id: Optional[str],
                             stats: Dict) -> None:
    """Emit and execute the batchUpdate requests for ``_insert_markdown``.

    Raises ``auth.DocsApiError`` on the first Google error envelope; ``stats``
    accumulates successfully executed batches/requests so the caller can report
    partial progress.

    Supported constructs:
      - ATX headings (#–######)
      - Paragraphs with **bold**, *italic*, `inline code`, [text](url)
      - Unordered lists (- item, * item) — createParagraphBullets config.BULLET_PRESET
      - Ordered lists (1. item) — createParagraphBullets NUMBERED_DECIMAL_ALPHA_ROMAN
      - Fenced code blocks (```) — Courier New paragraphs (config.CODE_FONT)
      - Blockquotes (> text) — italic, indented, with a left rule
      - Horizontal rules (---) — rendered as a line of ─ characters
      - Tables — real Docs tables via two-phase insertTable + cell insertText (reverse order)
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

    def _text_width_pt(resp: Dict) -> float:
        """Usable text width of the destination, in points (#1770).

        pageSize.width - marginLeft - marginRight, read from the destination's own
        documentStyle so a non-Letter page or non-1" margins produce a table that
        still spans exactly the text column. A tab carries its own
        documentTab.documentStyle; the doc body uses the top-level one. Any
        destination that reports no usable documentStyle falls back to
        config.FALLBACK_TEXT_WIDTH_PT (Letter, 1" margins).
        """
        style: Dict = {}
        if tab_id:
            tab = tabs._find_tab_by_id(resp.get("tabs", []), tab_id)
            if tab:
                style = tab.get("documentTab", {}).get("documentStyle", {}) or {}
        if not style:
            style = resp.get("documentStyle", {}) or {}

        def _mag(d: Any) -> Optional[float]:
            if isinstance(d, dict) and isinstance(d.get("magnitude"), (int, float)):
                return float(d["magnitude"])
            return None

        page = _mag((style.get("pageSize") or {}).get("width"))
        left = _mag(style.get("marginLeft"))
        right = _mag(style.get("marginRight"))
        if page is None or left is None or right is None:
            return float(config.FALLBACK_TEXT_WIDTH_PT)
        width = page - left - right
        # A pathological style (margins wider than the page) would yield a
        # zero/negative width that the API rejects; keep the house default.
        return width if width > 0 else float(config.FALLBACK_TEXT_WIDTH_PT)

    def _live_append_index(fallback: int) -> int:
        """Clamp a tab append to the live valid insertion point.

        Docs tab bodies reject structural inserts at the segment end index itself:
        appending must target the trailing paragraph boundary (endIndex - 1). After
        flushing a batch, our virtual current_index can equal the segment end, so
        re-read the tab and clamp before inserting tables/images.
        """
        if not tab_id:
            return fallback
        doc = auth.raise_for_error(
            auth.api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true")
        )
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

    def _run_batch(batch: List[Dict]) -> None:
        """Execute one batchUpdate and raise on a Google error envelope (#423).

        Responses were previously discarded here, which turned partial batch
        failures into silent truncation and total failures into silent empty
        tabs. Successful batches are counted in ``stats`` so a mid-flight
        failure can be reported as partial.
        """
        resp = auth.api(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            {"requests": batch},
        )
        auth.raise_for_error(resp)
        stats["batches"] += 1
        stats["requests"] += len(batch)

    def flush_requests() -> bool:
        nonlocal requests
        if not requests:
            return False
        for i in range(0, len(requests), 50):
            _run_batch(requests[i:i + 50])
        requests = []
        return True

    def paragraph_format_requests(rng: Dict, named_style: Optional[str]) -> List[Dict]:
        """Build the paragraph-level requests shared by every non-list paragraph.

        - updateParagraphStyle sets the named style ONLY. Spacing, fonts and
          sizes come from the named styles, which the house-style normalize pass
          pins per tab after every write (#2001, style_normalize.py).
        - deleteParagraphBullets clears any list bullet the paragraph inherited
          from the tab's anchor paragraph (#301 bug 1). It is the mirror of the
          #171 list-branch NORMAL_TEXT reset.
        """
        paragraph_style: Dict[str, Any] = {}
        fields: List[str] = []
        if named_style:
            paragraph_style["namedStyleType"] = named_style
            fields.append("namedStyleType")
        reqs: List[Dict] = []
        if fields:
            reqs.append({
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": paragraph_style,
                    "fields": ",".join(fields),
                }
            })
        reqs.append({"deleteParagraphBullets": {"range": rng}})
        return reqs

    def emit_blank_paragraph() -> None:
        """One empty NORMAL_TEXT paragraph — how hand-written docs chunk blocks (#1764)."""
        nonlocal current_index
        sync_to_live_append_index()
        location = _mk_location(current_index, tab_id)
        requests.append({"insertText": {"location": location, "text": "\n"}})
        end_idx = current_index + 1
        rng = _mk_range(current_index, end_idx, tab_id)
        requests.extend(paragraph_format_requests(rng, "NORMAL_TEXT"))
        current_index = end_idx

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
                    _walk_inlines(segment, segment_start, tab_id)
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

    def list_item_line_children(item: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
        """Inline children of EVERY paragraph in a list item, in document order.

        A tight item holds a single ``block_text``; a loose (multi-paragraph)
        item holds one ``paragraph`` per block. Only the first was rendered
        before (#528), so everything after the blank line vanished silently.
        """
        return [
            child.get("children", [])
            for child in item.get("children", [])
            if child.get("type") in ("block_text", "paragraph")
        ]

    def normal_text_reset(start: int, end: int) -> Dict[str, Any]:
        """Set a just-inserted list line to NORMAL_TEXT (#171) BEFORE its inline styles.

        Applying a namedStyleType resets the paragraph's text runs, even when the
        type is unchanged, so a reset issued after the inline styles wiped **bold**
        and `code` from every list item (found live, #2001). Pre-consumption
        range: it runs before createParagraphBullets deletes the nesting tabs.
        """
        return {"updateParagraphStyle": {
            "range": _mk_range(start, end, tab_id),
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "fields": "namedStyleType",
        }}

    def emit_list_line(children: List[Dict[str, Any]], prefix: str) -> None:
        """Insert one list paragraph: nesting prefix + inline content + newline.

        Lines with no image take the flat path — one insertText for the whole
        line. Lines containing an inline image take the segmented path (the
        mirror of ``emit_rich_paragraph``): text runs go in as text, image
        tokens as insertInlineImage. Flattening an image token yields "", so
        the flat path silently dropped the image and, for an image-only item,
        the whole line (#528).
        """
        nonlocal current_index, requests
        prefix_len = _utf16_len(prefix)
        line_begin = current_index

        if not _children_contain_image(children):
            insert_text = prefix + _plain_text_from_children(children) + "\n"
            line_start = current_index
            requests.append({
                "insertText": {
                    "location": _mk_location(line_start, tab_id),
                    "text": insert_text,
                }
            })
            requests.append(normal_text_reset(line_start, line_start + _utf16_len(insert_text)))
            requests.extend(
                _walk_inlines(children, line_start + prefix_len, tab_id)
            )
            current_index += _utf16_len(insert_text)
            return

        inline_requests: List[Dict] = []
        segment: List[Dict[str, Any]] = []
        pending = prefix  # nesting tabs ride along with the first text insert

        def flush_segment() -> None:
            nonlocal current_index, segment, pending
            text = pending + _plain_text_from_children(segment)
            if text:
                segment_start = current_index
                requests.append({
                    "insertText": {
                        "location": _mk_location(segment_start, tab_id),
                        "text": text,
                    }
                })
                inline_requests.extend(
                    _walk_inlines(
                        segment,
                        segment_start + _utf16_len(pending),
                        tab_id,
                    )
                )
                current_index += _utf16_len(text)
            segment = []
            pending = ""

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
        requests.append(normal_text_reset(line_begin, current_index))
        requests.extend(inline_requests)

    def emit_list_lines(list_token: Dict[str, Any], depth: int = 0,
                        tabs_before: int = 0) -> Tuple[int, List[Dict]]:
        """Insert all list item lines, preserving nested items with leading tabs.

        Returns ``(tabs_consumed, continuation_requests)``:

        - ``tabs_consumed`` is the running total UTF-16 length of leading
          nesting tabs inserted for the whole list, including ``tabs_before``.
          createParagraphBullets converts those tabs into bullet nesting levels
          and DELETES the characters, so the caller must shrink its virtual
          index accounting by this amount once bullets are applied (#298) —
          otherwise every later index in the batch is too high by the tab count
          and the write fails with "Index N must be less than the end index of
          the referenced segment".
        - ``continuation_requests`` are the fix-ups for the 2nd+ paragraph of a
          loose list item (#528). Those paragraphs are inserted as ordinary
          lines so their text survives, then un-bulleted and indented to the
          item's text column, so they read as continuations rather than as new
          bullets (which would also renumber an ordered list). They target
          post-consumption indexes and MUST be emitted after
          createParagraphBullets.
        """
        nonlocal current_index, requests
        sync_to_live_append_index()
        prefix = "\t" * depth
        prefix_len = _utf16_len(prefix)
        indent = {"magnitude": LIST_INDENT_PER_LEVEL_PT * (depth + 1), "unit": "PT"}
        consumed = tabs_before
        continuation_requests: List[Dict] = []

        for item in list_token.get("children", []):
            # `or [[]]`: an item with no paragraph at all (a bare "-") still gets a
            # line. Emitting nothing dropped the bullet entirely and renumbered
            # every following item of an ordered list (#528).
            for position, children in enumerate(list_item_line_children(item) or [[]]):
                tabs_before_line = consumed
                line_start = current_index
                emit_list_line(children, prefix)
                line_end = current_index
                consumed += prefix_len
                if position:
                    rng = _mk_range(line_start - tabs_before_line, line_end - consumed, tab_id)
                    continuation_requests.extend([
                        {"deleteParagraphBullets": {"range": rng}},
                        {
                            "updateParagraphStyle": {
                                "range": rng,
                                "paragraphStyle": {
                                    "indentStart": indent,
                                    "indentFirstLine": indent,
                                },
                                "fields": "indentStart,indentFirstLine",
                            }
                        },
                    ])
            for child in item.get("children", []):
                if child.get("type") == "list":
                    consumed, nested = emit_list_lines(child, depth + 1, consumed)
                    continuation_requests.extend(nested)
        return consumed, continuation_requests

    def next_block_type(pos: int) -> str:
        """Type of the next non-blank token after ``pos``, or "" at the end."""
        for later in tokens[pos + 1:]:
            if later.get("type") != "blank_line":
                return later.get("type", "")
        return ""

    previous_was_blank = True  # suppress a leading blank at the insertion point
    previous_block = ""
    for token_pos, token in enumerate(tokens):
        t = token.get("type", "")

        if t == "blank_line":
            # Preserve the author's chunking between prose blocks as one empty
            # paragraph per run (#1764). Never next to a heading: the heading's own
            # space-above separates sections in the house style (#2001). Never
            # before a table: insertTable creates its own empty paragraph above the
            # grid (PAIN-004).
            upcoming = next_block_type(token_pos)
            if (not previous_was_blank and previous_block != "heading"
                    and upcoming not in ("table", "heading", "")):
                emit_blank_paragraph()
                previous_was_blank = True
            continue
        # mistune folds the blank line that ends a list into the list token. A
        # prose block can only follow a list after a blank line, so restore it.
        if (previous_block == "list" and not previous_was_blank
                and t not in ("heading", "table", "list")):
            emit_blank_paragraph()
        previous_was_blank = False
        previous_block = t

        if t == "heading":
            level = token["attrs"]["level"]
            children = token.get("children", [])
            if _children_contain_image(children):
                current_index = emit_rich_paragraph(children, f"HEADING_{level}")
            else:
                text = _plain_text_from_children(children)
                inline_reqs = _walk_inlines(children, current_index, tab_id)
                current_index = emit_text_paragraph(text, inline_reqs, f"HEADING_{level}")

        elif t == "paragraph":
            children = token.get("children", [])
            if _children_contain_image(children):
                current_index = emit_rich_paragraph(children, "NORMAL_TEXT")
            else:
                text = _plain_text_from_children(children)
                inline_reqs = _walk_inlines(children, current_index, tab_id)
                current_index = emit_text_paragraph(text, inline_reqs, "NORMAL_TEXT")

        elif t == "block_quote":
            # Docs has no native blockquote type. The house shape is italic text,
            # indented 36pt, with a left rule — otherwise a quote is byte-for-byte
            # indistinguishable from body prose (#1768 PAIN-003).
            for child in token.get("children", []):
                if child.get("type") == "paragraph":
                    text = _plain_text_from_children(child.get("children", []))
                    insert_text = text + "\n"
                    sync_to_live_append_index()
                    location = _mk_location(current_index, tab_id)
                    requests.append({"insertText": {"location": location, "text": insert_text}})
                    end_idx = current_index + _utf16_len(insert_text)
                    rng = _mk_range(current_index, end_idx, tab_id)
                    # Bullet clearing FIRST: deleteParagraphBullets resets the
                    # paragraph's indentation, so running it after the style would
                    # wipe the quote indent (observed live on #1768).
                    requests.append({"deleteParagraphBullets": {"range": rng}})
                    quote_style: Dict[str, Any] = {"namedStyleType": "NORMAL_TEXT"}
                    indent = {"magnitude": config.BLOCK_QUOTE_INDENT_PT, "unit": "PT"}
                    quote_style["indentStart"] = indent
                    quote_style["indentFirstLine"] = indent
                    quote_style["borderLeft"] = config.BLOCK_QUOTE_BORDER
                    requests.append({
                        "updateParagraphStyle": {
                            "range": rng,
                            "paragraphStyle": quote_style,
                            "fields": "namedStyleType,indentStart,indentFirstLine,borderLeft",
                        }
                    })
                    requests.append({
                        "updateTextStyle": {
                            "range": rng,
                            "textStyle": {"italic": True},
                            "fields": "italic",
                        }
                    })
                    current_index = end_idx

        elif t == "block_code":
            # Fenced or indented code block. Docs exposes no code-block construct
            # over batchUpdate, so the reproducible shape is a monospace paragraph
            # run in config.CODE_FONT. No shading and no pinned size: the corpus
            # has zero non-empty paragraph shading, and the 9pt from the retired
            # 9pt code was refuted: 3 supporting runs against 104 with size absent.
            code_text = token.get("raw", "").rstrip("\n")
            insert_text = code_text + "\n"
            sync_to_live_append_index()
            location = _mk_location(current_index, tab_id)
            requests.append({"insertText": {"location": location, "text": insert_text}})
            end_idx = current_index + _utf16_len(insert_text)
            rng = _mk_range(current_index, end_idx, tab_id)
            # Paragraph style FIRST: applying namedStyleType after the text style
            # resets the run to the named style's font and drops the monospace
            # override (observed live on #1764).
            requests.append({
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    "fields": "namedStyleType",
                }
            })
            requests.append({"deleteParagraphBullets": {"range": rng}})
            requests.append({
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": {"weightedFontFamily": {"fontFamily": CODE_FONT}},
                    "fields": "weightedFontFamily",
                }
            })
            current_index = end_idx

        elif t == "thematic_break":
            # Render as a line of Unicode box-drawing horizontal chars
            hr_text = "─" * 40
            insert_text = hr_text + "\n"
            sync_to_live_append_index()
            location = _mk_location(current_index, tab_id)
            requests.append({"insertText": {"location": location, "text": insert_text}})
            end_idx = current_index + _utf16_len(insert_text)
            requests.extend(paragraph_format_requests(_mk_range(current_index, end_idx, tab_id), "NORMAL_TEXT"))
            current_index = end_idx

        elif t == "list":
            ordered = token.get("attrs", {}).get("ordered", False)
            glyph_preset = (config.ORDERED_BULLET_PRESET if ordered
                            else config.BULLET_PRESET)
            list_start = current_index

            # Insert all list item lines first, then add bullets in one request. Nested
            # list items use leading tabs, which Docs consumes as bullet nesting levels.
            tabs_consumed, continuation_requests = emit_list_lines(token)

            list_end = current_index
            rng = _mk_range(list_start, list_end, tab_id)
            requests.append({
                "createParagraphBullets": {
                    "range": rng,
                    "bulletPreset": glyph_preset,
                }
            })
            # createParagraphBullets DELETES the leading nesting tabs it just
            # consumed, shrinking the segment by tabs_consumed (#298). Every
            # request after this point — including the NORMAL_TEXT reset below —
            # must use post-consumption indexes, or a nested list makes the rest
            # of the batch fail with "Index N must be less than the end index of
            # the referenced segment". (Flat lists: tabs_consumed == 0, no-op.)
            list_end -= tabs_consumed
            current_index = list_end
            # #171 (list items must not inherit a preceding heading's style) is
            # handled per line in emit_list_line, before the inline styles — a
            # list-wide reset here would wipe them (#2001).
            # Loose-item continuation paragraphs (#528): un-bullet them and put
            # them back under the item's text column. They carry post-consumption
            # ranges, so they can only run after createParagraphBullets above.
            requests.extend(continuation_requests)

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
            _run_batch([
                {
                    "insertTable": {
                        "rows": num_rows,
                        "columns": num_cols,
                        "location": table_location,
                    }
                }
            ])

            # Phase 2: Discover cell start indices from the live document.
            get_url = f"https://docs.googleapis.com/v1/documents/{doc_id}"
            if tab_id:
                get_url += "?includeTabsContent=true"
            doc_resp = auth.raise_for_error(auth.api("GET", get_url))

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

            # insertTable also creates an empty paragraph immediately before the
            # grid. The normalize pass handles it (#2001): it inherits the pinned
            # NORMAL_TEXT style, and under a heading the heading merges onto it.

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
                # Cell paragraphs inherit the pinned NORMAL_TEXT style (#2001).
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
                    inline_reqs = _walk_inlines(cell_children, cell_start, tab_id)
                    cell_requests.extend(inline_reqs)

            if table_rows:
                table_start = _mk_location(matched_elem["startIndex"], tab_id)

                # Every cell is vertically centred, not just the header (#1770).
                # A header-only MIDDLE left body cells top-aligned, which reads as
                # a rendering bug in any row whose cells differ in height.
                cell_requests.append({
                    "updateTableCellStyle": {
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": table_start,
                                "rowIndex": 0,
                                "columnIndex": 0,
                            },
                            "rowSpan": len(table_rows),
                            "columnSpan": num_cols,
                        },
                        "tableCellStyle": {
                            "contentAlignment": config.TABLE_CELL_CONTENT_ALIGNMENT,
                        },
                        "fields": "contentAlignment",
                    }
                })

                # Grey tint on the header row sits on top of the whole-table
                # alignment: 48/48 tables in Randy's own corpus (#1768).
                cell_requests.append({
                    "updateTableCellStyle": {
                        "tableRange": {
                            "tableCellLocation": {
                                "tableStartLocation": table_start,
                                "rowIndex": 0,
                                "columnIndex": 0,
                            },
                            "rowSpan": 1,
                            "columnSpan": num_cols,
                        },
                        "tableCellStyle": {
                            "backgroundColor": {"color": {"rgbColor": config.TABLE_HEADER_TINT_RGB}},
                        },
                        "fields": "backgroundColor",
                    }
                })

                # Columns span the destination's full text width, split evenly
                # (#1770). insertTable's own widths shrink with column count, so a
                # 2-column table used to occupy half the page next to a 5-column
                # one; and the pre-#1769 175pt hard-code overflowed at 3 columns.
                col_width = _text_width_pt(doc_resp) / num_cols
                cell_requests.append({
                    "updateTableColumnProperties": {
                        "tableStartLocation": table_start,
                        "columnIndices": list(range(num_cols)),
                        "tableColumnProperties": {
                            "widthType": "FIXED_WIDTH",
                            "width": {"magnitude": col_width, "unit": "PT"},
                        },
                        "fields": "widthType,width",
                    }
                })
            if cell_requests:
                for i in range(0, len(cell_requests), 50):
                    _run_batch(cell_requests[i:i + 50])

            # Advance current_index past the table. matched_elem.endIndex is
            # the table's end BEFORE cell text was inserted; cell fills pushed
            # it forward by `inserted_chars`. Without that delta, following
            # paragraphs would land inside the last cell.
            current_index = matched_elem.get("endIndex", current_index) + inserted_chars

    # Execute in batches of 50
    flush_requests()
