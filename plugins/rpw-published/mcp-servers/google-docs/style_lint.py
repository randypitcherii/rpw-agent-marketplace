"""House-style lint for Google Docs (#2001).

Pure code over a ``documents.get?includeTabsContent=true`` payload. It resolves the
*effective* style of every paragraph and text run (NORMAL_TEXT → the paragraph's
named style → explicit overrides, the same cascade Docs uses) and compares it to
``house_style.json``. Because it checks effective values, a doc passes whether
its style comes from pinned named styles or from explicit per-paragraph values.

The result is a compact, content-free summary: violations grouped by
(rule, expected, actual) with a count and a few location samples. It never echoes
document text beyond a short locator snippet, so an agent can gate on it without
reading the doc back.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

SPEC_PATH = Path(__file__).resolve().parent / "house_style.json"

NAMED_STYLE_TYPES = (
    "NORMAL_TEXT", "HEADING_1", "HEADING_2", "HEADING_3", "HEADING_4",
    "HEADING_5", "HEADING_6", "TITLE", "SUBTITLE",
)
HEADING_TYPES = frozenset(t for t in NAMED_STYLE_TYPES if t != "NORMAL_TEXT")
ORDERED_GLYPH_TYPES = frozenset(
    {"DECIMAL", "ZERO_DECIMAL", "ALPHA", "UPPER_ALPHA", "ROMAN", "UPPER_ROMAN"})

# Docs' own defaults when nothing in the cascade sets a value.
DOCS_DEFAULT_LINE_SPACING = 100
DOCS_DEFAULT_MARGIN_PT = 72

MAX_SAMPLES = 2
MAX_GROUPS = 10
SNIPPET_CHARS = 24
TOLERANCE_PT = 0.05


# --- spec ---------------------------------------------------------------------

def load_spec(path: Path = SPEC_PATH) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def resolved_named_style(spec: Dict[str, Any], named_type: str) -> Dict[str, Any]:
    """The spec's values for one named style, with NORMAL_TEXT filling unset keys."""
    styles = spec["named_styles"]
    base = dict(styles["NORMAL_TEXT"])
    base.pop("color", None)  # colour is never inherited from body text in the spec
    own = styles.get(named_type) or {}
    return {**base, **own}


# --- small helpers ------------------------------------------------------------

def _mag(dim: Any) -> Optional[float]:
    if isinstance(dim, dict):
        return dim.get("magnitude", 0.0) if dim else None
    return None


def _first(*vals: Any) -> Any:
    for v in vals:
        if v is not None:
            return v
    return None


def _hex(color: Any) -> Optional[str]:
    """foregroundColor → '#rrggbb'. An explicitly empty rgbColor is black."""
    if not isinstance(color, dict) or "color" not in color:
        return None
    rgb = (color.get("color") or {}).get("rgbColor")
    if rgb is None:
        return None
    return "#" + "".join(f"{round(rgb.get(c, 0.0) * 255):02x}" for c in ("red", "green", "blue"))


def _eq(a: Optional[float], b: Optional[float]) -> bool:
    if a is None or b is None:
        return a == b
    return abs(a - b) <= TOLERANCE_PT


def _fmt(v: Any) -> Any:
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _para_text(p: Dict[str, Any]) -> str:
    return "".join((e.get("textRun") or {}).get("content", "") for e in p.get("elements", []))


def _is_blank(p: Dict[str, Any]) -> bool:
    if p.get("bullet"):
        return False
    if any("textRun" not in e for e in p.get("elements", [])):
        return False  # images, chips, etc. are content
    return _para_text(p).strip() == ""


# --- effective-style resolution -----------------------------------------------

class _DocStyles:
    """The doc's own named styles, keyed by type, for cascade resolution."""

    def __init__(self, named_styles: Dict[str, Any]):
        self.by_type = {s.get("namedStyleType"): s for s in (named_styles or {}).get("styles", [])}

    def _layers(self, named_type: str, key: str) -> List[Dict[str, Any]]:
        normal = (self.by_type.get("NORMAL_TEXT") or {}).get(key) or {}
        own = (self.by_type.get(named_type) or {}).get(key) or {} if named_type != "NORMAL_TEXT" else {}
        return [own, normal]

    def para(self, named_type: str, explicit: Dict[str, Any]) -> Dict[str, Any]:
        layers = [explicit] + self._layers(named_type, "paragraphStyle")
        return {
            "line_spacing": _first(*(l.get("lineSpacing") for l in layers), DOCS_DEFAULT_LINE_SPACING),
            "space_above_pt": _first(*(_mag(l.get("spaceAbove")) for l in layers), 0.0),
            "space_below_pt": _first(*(_mag(l.get("spaceBelow")) for l in layers), 0.0),
        }

    def text(self, named_type: str, explicit: Dict[str, Any]) -> Dict[str, Any]:
        layers = [explicit] + self._layers(named_type, "textStyle")
        return {
            "font_family": _first(*((l.get("weightedFontFamily") or {}).get("fontFamily") for l in layers)),
            "font_size_pt": _first(*(_mag(l.get("fontSize")) for l in layers)),
            "bold": bool(_first(*(l.get("bold") for l in layers), False)),
            "color": _first(*(_hex(l.get("foregroundColor")) for l in layers)),
        }


# --- the linter -----------------------------------------------------------------

class _Report:
    def __init__(self) -> None:
        self.groups: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        self.checked = {"tabs": 0, "paragraphs": 0, "runs": 0, "tables": 0}
        # Machine-readable repairs, one per violation that normalize can fix
        # (style_normalize.py). Not part of the lint output.
        self.fixes: List[Dict[str, Any]] = []

    def add(self, rule: str, severity: str, expected: Any, actual: Any, where: str,
            fix: Optional[Dict[str, Any]] = None) -> None:
        if fix is not None:
            self.fixes.append(fix)
        key = (rule, severity, json.dumps(_fmt(expected)), json.dumps(_fmt(actual)))
        g = self.groups.setdefault(key, {
            "rule": rule, "severity": severity, "expected": _fmt(expected),
            "actual": _fmt(actual), "count": 0, "samples": []})
        g["count"] += 1
        if len(g["samples"]) < MAX_SAMPLES:
            g["samples"].append(where)

    def result(self) -> Dict[str, Any]:
        groups = sorted(self.groups.values(),
                        key=lambda g: (g["severity"] != "error", -g["count"], g["rule"]))
        errors = sum(g["count"] for g in groups if g["severity"] == "error")
        warnings = sum(g["count"] for g in groups if g["severity"] != "error")
        by_rule: Dict[str, int] = {}
        for g in groups:
            by_rule[g["rule"]] = by_rule.get(g["rule"], 0) + g["count"]
        out = {"ok": errors == 0, "errors": errors, "warnings": warnings,
               "checked": dict(self.checked),
               "by_rule": dict(sorted(by_rule.items(), key=lambda kv: -kv[1])),
               "violations": groups[:MAX_GROUPS]}
        if len(groups) > MAX_GROUPS:
            out["truncated_groups"] = len(groups) - MAX_GROUPS
        return out


def _walk_tabs(tabs: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    for t in tabs or []:
        yield t
        yield from _walk_tabs(t.get("childTabs") or [])


def select_tabs(document: Dict[str, Any], tab_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every tab (child tabs included), or just ``tab_id``. Raises ValueError if absent."""
    tabs = list(_walk_tabs(document.get("tabs") or []))
    if tab_id is not None:
        tabs = [t for t in tabs if (t.get("tabProperties") or {}).get("tabId") == tab_id]
        if not tabs:
            raise ValueError(f"tab not found: {tab_id}")
    return tabs


def lint_document(document: Dict[str, Any], spec: Optional[Dict[str, Any]] = None,
                  tab_id: Optional[str] = None) -> Dict[str, Any]:
    """Lint a documents.get payload (fetched with includeTabsContent=true)."""
    spec = spec or load_spec()
    report = _Report()
    for tab in select_tabs(document, tab_id):
        _TabLinter(tab, spec, report).run()
    return report.result()


def tab_fixes(tab: Dict[str, Any], spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The repairs for one tab's violations, as recorded by the linter (for normalize)."""
    report = _Report()
    _TabLinter(tab, spec, report).run()
    return report.fixes


class _TabLinter:
    def __init__(self, tab: Dict[str, Any], spec: Dict[str, Any], report: _Report):
        self.spec = spec
        self.report = report
        self.dt = tab.get("documentTab") or {}
        self.tab_title = (tab.get("tabProperties") or {}).get("title", "?")
        self.tab_id = (tab.get("tabProperties") or {}).get("tabId")
        self.styles = _DocStyles(self.dt.get("namedStyles") or {})
        self.lists = self.dt.get("lists") or {}
        self.para_no = 0
        code = spec.get("code") or {}
        self.code_fonts = set(code.get("allowed_font_families") or [code.get("font_family")])

    # location strings are the only doc-derived text in the output
    def _where(self, p: Optional[Dict[str, Any]] = None, extra: str = "") -> str:
        loc = f"{self.tab_title} ¶{self.para_no}"
        if p is not None:
            t = _para_text(p).strip().replace("\n", " ")
            style = (p.get("paragraphStyle") or {}).get("namedStyleType", "NORMAL_TEXT")
            snippet = (t[:SNIPPET_CHARS] + "…") if len(t) > SNIPPET_CHARS else t
            loc += f" {style} “{snippet}”"
        return loc + extra

    def run(self) -> None:
        self.report.checked["tabs"] += 1
        self._check_page()
        self._check_named_styles()
        self._check_blocks(((self.dt.get("body") or {}).get("content") or []), top_level=True)

    # -- document level
    def _check_page(self) -> None:
        page = self.spec.get("page")
        if not page:
            return
        ds = self.dt.get("documentStyle") or {}
        size = ds.get("pageSize") or {}
        w, h = _mag(size.get("width")), _mag(size.get("height"))
        if w is not None and h is not None and not (_eq(w, page["width_pt"]) and _eq(h, page["height_pt"])):
            self.report.add("page.size", "error", [page["width_pt"], page["height_pt"]], [w, h], self.tab_title,
                            fix={"kind": "page", "tab_id": self.tab_id})
        for side in ("Top", "Bottom", "Left", "Right"):
            m = _first(_mag(ds.get(f"margin{side}")), DOCS_DEFAULT_MARGIN_PT)
            if not _eq(m, page["margin_pt"]):
                self.report.add("page.margin", "error", page["margin_pt"], m, f"{self.tab_title} margin{side}",
                                fix={"kind": "page", "tab_id": self.tab_id})

    def _check_named_styles(self) -> None:
        for t in NAMED_STYLE_TYPES:
            if t not in self.styles.by_type:
                continue
            for key, want, got in named_style_diffs(self.styles, self.spec, t):
                self.report.add(f"named_style.{key.replace('_pt', '')}", "error", want, got,
                                f"{self.tab_title} {t}")

    # -- content
    def _check_blocks(self, content: List[Dict[str, Any]], top_level: bool, in_table: bool = False) -> None:
        blocks = [el for el in content if "paragraph" in el or "table" in el]
        last = len(blocks) - 1
        blank_run = 0
        for i, el in enumerate(blocks):
            if "table" in el:
                blank_run = 0
                self._check_table(dict(el["table"], _startIndex=el.get("startIndex")))
                continue
            p = el["paragraph"]
            self.para_no += 1
            is_anchor = top_level and i == last
            if is_anchor and _is_blank(p):
                continue  # Docs' tab-end anchor paragraph
            self.report.checked["paragraphs"] += 1
            self._check_paragraph(el)
            if in_table:
                continue
            if _is_blank(p):
                blank_run += 1
                if blank_run > self.spec["blank_paragraphs"]["max_consecutive"]:
                    self.report.add("blank.consecutive", "error",
                                    self.spec["blank_paragraphs"]["max_consecutive"], blank_run, self._where())
                if not self.spec["blank_paragraphs"]["allow_adjacent_to_heading"]:
                    neighbours = [blocks[j] for j in (i - 1, i + 1) if 0 <= j <= last]
                    if any(_heading(n) for n in neighbours):
                        self.report.add("blank.adjacent_heading", "error", "no blank paragraph",
                                        "blank paragraph", self._where())
            else:
                blank_run = 0

    def _check_paragraph(self, el: Dict[str, Any]) -> None:
        p = el["paragraph"]
        span = (el.get("startIndex"), el.get("endIndex"))
        ps = p.get("paragraphStyle") or {}
        t = ps.get("namedStyleType")
        if t not in NAMED_STYLE_TYPES:
            t = "NORMAL_TEXT"
        want = resolved_named_style(self.spec, t)
        got = self.styles.para(t, ps)
        for key in ("line_spacing", "space_above_pt", "space_below_pt"):
            if not _same(want[key], got[key]):
                self.report.add(f"paragraph.{key.replace('_pt', '')}", "error", want[key], got[key], self._where(p),
                                fix={"kind": "paragraph_reset", "tab_id": self.tab_id, "span": span,
                                     "field": _PARA_FIELDS[key]})
        if p.get("bullet"):
            self._check_list_item(p, ps, span)
        for e in p.get("elements", []):
            run = e.get("textRun")
            if not run or not run.get("content"):
                continue
            self.report.checked["runs"] += 1
            self._check_run(p, t, want, e)

    def _check_run(self, p: Dict[str, Any], t: str, want: Dict[str, Any], e: Dict[str, Any]) -> None:
        run = e["textRun"]
        ts = run.get("textStyle") or {}

        def reset(field: str) -> Dict[str, Any]:
            return {"kind": "run_reset", "tab_id": self.tab_id,
                    "span": (e.get("startIndex"), e.get("endIndex")), "field": field}

        got = self.styles.text(t, ts)
        visible = run.get("content", "").strip() != ""
        if got["font_family"] != want["font_family"] and got["font_family"] not in self.code_fonts:
            self.report.add("run.font_family", "error", want["font_family"], got["font_family"], self._where(p),
                            fix=reset("weightedFontFamily"))
        if not _same(want["font_size_pt"], got["font_size_pt"]):
            self.report.add("run.font_size", "error", want["font_size_pt"], got["font_size_pt"], self._where(p),
                            fix=reset("fontSize"))
        if visible and t in HEADING_TYPES and want.get("bold") and not got["bold"]:
            self.report.add("run.bold", "error", True, False, self._where(p), fix=reset("bold"))
        if visible and want.get("color") and not ts.get("link") and got["color"] != want["color"].lower():
            self.report.add("run.color", "error", want["color"].lower(), got["color"], self._where(p),
                            fix=reset("foregroundColor"))

    def _check_list_item(self, p: Dict[str, Any], ps: Dict[str, Any], span: Tuple[Any, Any]) -> None:
        spec = self.spec["lists"]
        b = p["bullet"]
        levels = ((self.lists.get(b.get("listId")) or {}).get("listProperties") or {}).get("nestingLevels") or []
        lvl = b.get("nestingLevel", 0) or 0
        nl = levels[lvl] if lvl < len(levels) else {}
        ordered = nl.get("glyphType") in ORDERED_GLYPH_TYPES
        if not ordered:
            glyph = nl.get("glyphSymbol")
            if glyph != spec["unordered_glyph"]:
                self.report.add("list.glyph", spec.get("unordered_glyph_severity", "error"),
                                spec["unordered_glyph"], glyph, self._where(p))
        start = _first(_mag(ps.get("indentStart")), _mag(nl.get("indentStart")), 0.0)
        first = _first(_mag(ps.get("indentFirstLine")), _mag(nl.get("indentFirstLine")), 0.0)
        step, hang = spec["indent_step_pt"], spec["hanging_indent_pt"]
        on_ladder = start >= step - TOLERANCE_PT and abs(start / step - round(start / step)) * step <= TOLERANCE_PT
        if not on_ladder or not _eq(first, start - hang):
            depth = max(1, round(start / step))
            self.report.add("list.indent", "error", [depth * step, depth * step - hang], [start, first],
                            self._where(p),
                            fix={"kind": "list_indent", "tab_id": self.tab_id, "span": span,
                                 "indent_start": depth * step, "indent_first_line": depth * step - hang})

    def _check_table(self, tbl: Dict[str, Any]) -> None:
        spec = self.spec.get("tables") or {}
        self.report.checked["tables"] += 1
        where = f"{self.tab_title} table after ¶{self.para_no}"
        table_start = tbl.get("_startIndex")
        n_rows, n_cols = tbl.get("rows", 0), tbl.get("columns", 0)
        for r, row in enumerate(tbl.get("tableRows") or []):
            for cell in row.get("tableCells") or []:
                align = (cell.get("tableCellStyle") or {}).get("contentAlignment", "TOP")
                if spec.get("cell_content_alignment") and align != spec["cell_content_alignment"]:
                    self.report.add("table.cell_alignment", "error", spec["cell_content_alignment"], align, where,
                                    fix={"kind": "table_align", "tab_id": self.tab_id, "table_start": table_start,
                                         "rows": n_rows, "columns": n_cols,
                                         "alignment": spec["cell_content_alignment"]})
                if r == 0 and spec.get("header_row_bold"):
                    for el in cell.get("content") or []:
                        for e in (el.get("paragraph") or {}).get("elements", []):
                            run = e.get("textRun") or {}
                            if run.get("content", "").strip() and not self.styles.text(
                                    "NORMAL_TEXT", run.get("textStyle") or {})["bold"]:
                                self.report.add("table.header_bold", "error", True, False, where,
                                                fix={"kind": "run_bold", "tab_id": self.tab_id,
                                                     "span": (e.get("startIndex"), e.get("endIndex"))})
                self._check_blocks(cell.get("content") or [], top_level=False, in_table=True)
        if spec.get("full_text_width"):
            cols = (tbl.get("tableStyle") or {}).get("tableColumnProperties") or []
            if cols and all(c.get("widthType") == "FIXED_WIDTH" and c.get("width") for c in cols):
                total = sum(_mag(c["width"]) or 0.0 for c in cols)
                text_w = self._text_width()
                if abs(total - text_w) > spec.get("width_tolerance_pt", 1):
                    self.report.add("table.width", "error", text_w, round(total, 2), where,
                                    fix={"kind": "table_width", "tab_id": self.tab_id, "table_start": table_start,
                                         "columns": len(cols), "width_pt": text_w})

    def _text_width(self) -> float:
        ds = self.dt.get("documentStyle") or {}
        width = _first(_mag((ds.get("pageSize") or {}).get("width")), self.spec["page"]["width_pt"])
        left = _first(_mag(ds.get("marginLeft")), DOCS_DEFAULT_MARGIN_PT)
        right = _first(_mag(ds.get("marginRight")), DOCS_DEFAULT_MARGIN_PT)
        return width - left - right


_PARA_FIELDS = {"line_spacing": "lineSpacing", "space_above_pt": "spaceAbove", "space_below_pt": "spaceBelow"}


def named_style_diffs(styles: "_DocStyles", spec: Dict[str, Any], named_type: str) -> List[Tuple[str, Any, Any]]:
    """(key, expected, actual) for each way the doc's named style differs from the spec."""
    want = resolved_named_style(spec, named_type)
    got = {**styles.para(named_type, {}), **styles.text(named_type, {})}
    out = [(k, want.get(k), got.get(k))
           for k in ("font_family", "font_size_pt", "bold", "line_spacing", "space_above_pt", "space_below_pt")
           if not _same(want.get(k), got.get(k))]
    if want.get("color") and got.get("color") != want["color"].lower():
        out.append(("color", want["color"].lower(), got.get("color")))
    return out


def _heading(block: Dict[str, Any]) -> bool:
    p = block.get("paragraph")
    return bool(p) and (p.get("paragraphStyle") or {}).get("namedStyleType") in HEADING_TYPES


def _same(want: Any, got: Any) -> bool:
    if isinstance(want, (int, float)) and not isinstance(want, bool) and isinstance(got, (int, float)):
        return _eq(float(want), float(got))
    return want == got
