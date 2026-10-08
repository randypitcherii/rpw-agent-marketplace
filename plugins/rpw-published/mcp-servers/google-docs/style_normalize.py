"""House-style normalize pass for Google Docs (#2001).

``normalize_requests`` turns a ``documents.get?includeTabsContent=true`` payload into
the ``batchUpdate`` requests that bring each tab to ``house_style.json``. It is pure:
no network, and the requests come out in the order they must run.

How it works, per tab:

1. **Pin the named styles** (``updateNamedStyle``, tab-scoped) for every named style
   whose definition differs from the spec.
2. **Lint the tab as if step 1 had already run.** The spec's named styles are used as
   the baseline, so any remaining violation is an explicit override. Each one is
   repaired the way the linter recorded it (``style_lint.tab_fixes``). Most repairs
   *reset* the override so the paragraph or run inherits the pinned named style,
   which gives the same structure as the hand-built template.
3. **Delete extra blank paragraphs** last, in descending index order, so earlier
   requests keep valid indices. Docs requires a paragraph before a table, so that
   one is never deleted. When it sits under a heading, the heading's newline is
   deleted instead, which merges the heading onto it.

Normalize and lint share one traversal, so a normalized tab lints clean (except
warnings the API cannot fix, such as dash bullet glyphs), and a second normalize
emits no requests.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

import style_lint
from style_lint import NAMED_STYLE_TYPES, _heading, _is_blank

_NAMED_STYLE_FIELDS = ",".join([
    "namedStyleType",
    "textStyle.weightedFontFamily", "textStyle.fontSize", "textStyle.bold", "textStyle.foregroundColor",
    "paragraphStyle.lineSpacing", "paragraphStyle.spaceAbove", "paragraphStyle.spaceBelow",
])


def _pt(v: float) -> Dict[str, Any]:
    return {"magnitude": v, "unit": "PT"}


def _rgb(hex_color: str) -> Dict[str, Any]:
    h = hex_color.lstrip("#")
    return {"color": {"rgbColor": {c: int(h[i:i + 2], 16) / 255 for c, i in
                                   (("red", 0), ("green", 2), ("blue", 4))}}}


def spec_named_style(spec: Dict[str, Any], named_type: str) -> Dict[str, Any]:
    """One named style from the spec, in documents.get / updateNamedStyle shape."""
    s = style_lint.resolved_named_style(spec, named_type)
    text: Dict[str, Any] = {
        "weightedFontFamily": {"fontFamily": s["font_family"]},
        "fontSize": _pt(s["font_size_pt"]),
        "bold": bool(s["bold"]),
    }
    if s.get("color"):
        text["foregroundColor"] = _rgb(s["color"])
    return {
        "namedStyleType": named_type,
        "textStyle": text,
        "paragraphStyle": {
            "lineSpacing": s["line_spacing"],
            "spaceAbove": _pt(s["space_above_pt"]),
            "spaceBelow": _pt(s["space_below_pt"]),
        },
    }


def _named_style_requests(tab: Dict[str, Any], spec: Dict[str, Any], tab_id: str) -> List[Dict[str, Any]]:
    styles = style_lint._DocStyles((tab.get("documentTab") or {}).get("namedStyles") or {})
    wrong = [t for t in NAMED_STYLE_TYPES
             if t not in styles.by_type or style_lint.named_style_diffs(styles, spec, t)]
    return [{"updateNamedStyle": {"tabId": tab_id, "namedStyle": spec_named_style(spec, t),
                                  "fields": _NAMED_STYLE_FIELDS}} for t in wrong]


def _style_requests(fixes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Non-index-changing repairs, deduplicated and merged per range."""
    para: Dict[Tuple[int, int], List[str]] = {}
    runs: Dict[Tuple[int, int], List[str]] = {}
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for f in fixes:
        kind, tid = f["kind"], f["tab_id"]
        span = f.get("span")
        if span is not None and (span[0] is None or span[1] is None):
            continue  # no indices (synthetic payloads) — nothing addressable
        if kind == "paragraph_reset":
            para.setdefault(span, [])
            if f["field"] not in para[span]:
                para[span].append(f["field"])
        elif kind == "run_reset":
            runs.setdefault(span, [])
            if f["field"] not in runs[span]:
                runs[span].append(f["field"])
        elif kind == "run_bold":
            if ("bold", span) not in seen:
                seen.add(("bold", span))
                out.append({"updateTextStyle": {"range": _range(span, tid), "textStyle": {"bold": True},
                                                "fields": "bold"}})
        elif kind == "list_indent":
            out.append({"updateParagraphStyle": {
                "range": _range(span, tid),
                "paragraphStyle": {"indentStart": _pt(f["indent_start"]),
                                   "indentFirstLine": _pt(f["indent_first_line"])},
                "fields": "indentStart,indentFirstLine"}})
        elif kind == "table_align":
            key = ("align", f["table_start"])
            if key in seen or f["table_start"] is None:
                continue
            seen.add(key)
            out.append({"updateTableCellStyle": {
                "tableRange": {"tableCellLocation": {"tableStartLocation": _loc(f["table_start"], tid),
                                                     "rowIndex": 0, "columnIndex": 0},
                               "rowSpan": f["rows"], "columnSpan": f["columns"]},
                "tableCellStyle": {"contentAlignment": f["alignment"]},
                "fields": "contentAlignment"}})
        elif kind == "table_width":
            key = ("width", f["table_start"])
            if key in seen or f["table_start"] is None:
                continue
            seen.add(key)
            out.append({"updateTableColumnProperties": {
                "tableStartLocation": _loc(f["table_start"], tid),
                "columnIndices": list(range(f["columns"])),
                "tableColumnProperties": {"widthType": "FIXED_WIDTH",
                                          "width": _pt(round(f["width_pt"] / f["columns"], 2))},
                "fields": "widthType,width"}})
    tid = fixes[0]["tab_id"]
    for span, fields in para.items():
        out.append({"updateParagraphStyle": {"range": _range(span, tid), "paragraphStyle": {},
                                             "fields": ",".join(fields)}})
    for span, fields in runs.items():
        out.append({"updateTextStyle": {"range": _range(span, tid), "textStyle": {},
                                        "fields": ",".join(fields)}})
    return out


def _page_requests(tab: Dict[str, Any], spec: Dict[str, Any], tab_id: str) -> List[Dict[str, Any]]:
    fixes = [f for f in style_lint.tab_fixes(tab, spec) if f["kind"] == "page"]
    if not fixes:
        return []
    page = spec["page"]
    m = _pt(page["margin_pt"])
    return [{"updateDocumentStyle": {
        "tabId": tab_id,
        "documentStyle": {"pageSize": {"width": _pt(page["width_pt"]), "height": _pt(page["height_pt"])},
                          "marginTop": m, "marginBottom": m, "marginLeft": m, "marginRight": m},
        "fields": "pageSize,marginTop,marginBottom,marginLeft,marginRight"}}]


def _blank_requests(tab: Dict[str, Any], spec: Dict[str, Any], tab_id: str) -> List[Dict[str, Any]]:
    """Delete extra blank paragraphs, highest index first."""
    rules = spec["blank_paragraphs"]
    content = ((tab.get("documentTab") or {}).get("body") or {}).get("content") or []
    blocks = [el for el in content if "paragraph" in el or "table" in el]
    if not blocks:
        return []
    last = len(blocks) - 1
    ops: List[Tuple[int, List[Dict[str, Any]]]] = []

    def is_blank(i: int) -> bool:
        el = blocks[i]
        return "paragraph" in el and _is_blank(el["paragraph"]) and i != last

    i = 0
    while i <= last:
        if not is_blank(i):
            i += 1
            continue
        j = i
        while j + 1 <= last and is_blank(j + 1):
            j += 1
        run = blocks[i:j + 1]
        prev = blocks[i - 1] if i > 0 else None
        nxt = blocks[j + 1] if j + 1 <= last else None
        near_heading = (prev is not None and _heading(prev)) or (nxt is not None and _heading(nxt))
        keep = 0 if (near_heading and not rules["allow_adjacent_to_heading"]) else rules["max_consecutive"]
        if nxt is not None and "table" in nxt:
            deletable = run[:-1]  # Docs requires the paragraph right before a table
            extra = max(0, len(deletable) + 1 - keep)
            for el in deletable[:extra]:
                ops.append(_delete(el, tab_id))
            if keep == 0 and prev is not None and _heading(prev):
                ops.append(_merge_heading_down(prev, tab_id))
        else:
            for el in run[keep:]:
                ops.append(_delete(el, tab_id))
        i = j + 1
    ops.sort(key=lambda op: -op[0])
    return [r for _, reqs in ops for r in reqs]


def _delete(el: Dict[str, Any], tab_id: str) -> Tuple[int, List[Dict[str, Any]]]:
    s, e = el["startIndex"], el["endIndex"]
    return s, [{"deleteContentRange": {"range": _range((s, e), tab_id)}}]


def _merge_heading_down(heading_el: Dict[str, Any], tab_id: str) -> Tuple[int, List[Dict[str, Any]]]:
    """Delete a heading's newline so its text joins the required pre-table paragraph.

    The surviving paragraph keeps the blank's (NORMAL_TEXT) style, so the heading's
    named style is re-applied to the merged range. Verified live (#2001).
    """
    s, e = heading_el["startIndex"], heading_el["endIndex"]
    named = heading_el["paragraph"]["paragraphStyle"]["namedStyleType"]
    return e - 1, [
        {"deleteContentRange": {"range": _range((e - 1, e), tab_id)}},
        {"updateParagraphStyle": {"range": _range((s, e), tab_id),
                                  "paragraphStyle": {"namedStyleType": named}, "fields": "namedStyleType"}},
    ]


def _range(span: Tuple[int, int], tab_id: Optional[str]) -> Dict[str, Any]:
    r: Dict[str, Any] = {"startIndex": span[0], "endIndex": span[1]}
    if tab_id:
        r["tabId"] = tab_id
    return r


def _loc(index: int, tab_id: Optional[str]) -> Dict[str, Any]:
    loc: Dict[str, Any] = {"index": index}
    if tab_id:
        loc["tabId"] = tab_id
    return loc


def normalize_tab_requests(tab: Dict[str, Any], spec: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    spec = spec or style_lint.load_spec()
    tab_id = (tab.get("tabProperties") or {}).get("tabId")
    requests = _named_style_requests(tab, spec, tab_id)
    requests += _page_requests(tab, spec, tab_id)
    # Lint as if the named styles were already pinned: what remains is overrides.
    pinned = copy.deepcopy(tab)
    pinned.setdefault("documentTab", {})["namedStyles"] = {
        "styles": [spec_named_style(spec, t) for t in NAMED_STYLE_TYPES]}
    fixes = [f for f in style_lint.tab_fixes(pinned, spec) if f["kind"] != "page"]
    if fixes:
        requests += _style_requests(fixes)
    requests += _blank_requests(tab, spec, tab_id)
    return requests


def normalize_requests(document: Dict[str, Any], spec: Optional[Dict[str, Any]] = None,
                       tab_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """All requests to normalize the doc (or one tab), in execution order."""
    spec = spec or style_lint.load_spec()
    out: List[Dict[str, Any]] = []
    for tab in style_lint.select_tabs(document, tab_id):
        out += normalize_tab_requests(tab, spec)
    return out
