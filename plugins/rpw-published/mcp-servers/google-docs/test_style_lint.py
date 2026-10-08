#!/usr/bin/env python3
"""Tests for style_lint (#2001): a code-only house-style check over documents.get JSON.

Every payload here is synthetic, built by the helpers below. No network, no real doc.
"""

import copy
import json
import unittest

import style_lint

SPEC = style_lint.load_spec()


# --- payload builders -------------------------------------------------------

def pt(v):
    return {"magnitude": v, "unit": "PT"}


def jam_named_styles():
    """The template's named styles, in documents.get shape."""
    def style(t, ts=None, ps=None):
        return {"namedStyleType": t, "textStyle": ts or {}, "paragraphStyle": ps or {}}
    grey = {"color": {"rgbColor": {"red": 0.4, "green": 0.4, "blue": 0.4}}}
    return {"styles": [
        style("NORMAL_TEXT",
              {"weightedFontFamily": {"fontFamily": "Arial"}, "fontSize": pt(13), "bold": False},
              {"lineSpacing": 115, "spaceAbove": pt(0), "spaceBelow": pt(0)}),
        style("HEADING_1", {"fontSize": pt(22), "bold": True}, {"spaceAbove": pt(20), "spaceBelow": pt(6)}),
        style("HEADING_2", {"fontSize": pt(18), "bold": True}, {"spaceAbove": pt(18), "spaceBelow": pt(6)}),
        style("HEADING_3", {"fontSize": pt(16), "bold": True}, {"spaceAbove": pt(16), "spaceBelow": pt(4)}),
        style("HEADING_4", {"fontSize": pt(12), "foregroundColor": grey}, {"spaceAbove": pt(14), "spaceBelow": pt(4)}),
        style("HEADING_5", {"fontSize": pt(11), "foregroundColor": grey}, {"spaceAbove": pt(12), "spaceBelow": pt(4)}),
        style("HEADING_6", {"fontSize": pt(11), "foregroundColor": grey}, {"spaceAbove": pt(12), "spaceBelow": pt(4)}),
        style("TITLE", {"fontSize": pt(26)}, {"spaceBelow": pt(3)}),
        style("SUBTITLE", {"weightedFontFamily": {"fontFamily": "Arial"}, "fontSize": pt(15), "foregroundColor": grey},
              {"spaceBelow": pt(16)}),
    ]}


def para(text, style="NORMAL_TEXT", ps=None, runs=None, bullet=None):
    """A paragraph element. runs: list of (content, textStyle); default one plain run."""
    if runs is None:
        runs = [(text + "\n", {})]
    p = {"elements": [{"textRun": {"content": c, "textStyle": ts}} for c, ts in runs],
         "paragraphStyle": dict({"namedStyleType": style}, **(ps or {}))}
    if bullet is not None:
        p["bullet"] = bullet
    return {"paragraph": p}


def dash_list(list_id="L1"):
    return {list_id: {"listProperties": {"nestingLevels": [
        {"glyphSymbol": "-", "indentStart": pt(36 * (i + 1)), "indentFirstLine": pt(36 * (i + 1) - 18)}
        for i in range(9)]}}}


def item(text, level=0, list_id="L1", ps=None):
    base = {"indentStart": pt(36 * (level + 1)), "indentFirstLine": pt(36 * (level + 1) - 18)}
    base.update(ps or {})
    return para(text, ps=base, bullet={"listId": list_id, "nestingLevel": level})


def table(rows, widths=(234, 234), align="MIDDLE", header_bold=True, cell_ps=None):
    trs = []
    for r, row in enumerate(rows):
        cells = []
        for text in row:
            ts = {"bold": True} if (r == 0 and header_bold) else {}
            cells.append({"content": [para(text, ps=cell_ps, runs=[(text + "\n", ts)])],
                          "tableCellStyle": {"contentAlignment": align}})
        trs.append({"tableCells": cells})
    return {"table": {"rows": len(rows), "columns": len(rows[0]), "tableRows": trs,
                      "tableStyle": {"tableColumnProperties": [
                          {"widthType": "FIXED_WIDTH", "width": pt(w)} for w in widths]}}}


def doc(content, named=None, lists=None, doc_style=None, tab_id="t.0", title="Tab 1", child_tabs=None):
    body = [{"sectionBreak": {}}] + content + [para("")]  # trailing blank = tab-end anchor
    ds = doc_style if doc_style is not None else {
        "pageSize": {"width": pt(612), "height": pt(792)},
        "marginTop": pt(72), "marginBottom": pt(72), "marginLeft": pt(72), "marginRight": pt(72)}
    return {"documentId": "fake", "tabs": [{
        "tabProperties": {"tabId": tab_id, "title": title},
        "documentTab": {"body": {"content": body}, "documentStyle": ds,
                        "namedStyles": named if named is not None else jam_named_styles(),
                        "lists": lists if lists is not None else dash_list()},
        "childTabs": child_tabs or []}]}


def jam_doc():
    return doc([
        para("2026-09-28 – topic", "HEADING_1"),
        para("🔥 Top Priorities Hot box 🔥", "HEADING_2"),
        item("the one thing"),
        item("a nested thing", level=1),
        para("🤕 Active Pains", "HEADING_2"),
        para("Body prose with `code`.", runs=[("Body prose with ", {}),
                                              ("code", {"weightedFontFamily": {"fontFamily": "Courier New"}}),
                                              (".\n", {"bold": True})]),
        para(""),
        para("Another chunk of prose."),
        table([["Col A", "Col B"], ["a", "b"]]),
    ])


def rules(result, severity=None):
    return {v["rule"] for v in result["violations"] if severity is None or v["severity"] == severity}


# --- tests --------------------------------------------------------------------

class TestSpec(unittest.TestCase):
    def test_resolved_styles_inherit_normal_text(self):
        h1 = style_lint.resolved_named_style(SPEC, "HEADING_1")
        self.assertEqual(h1["font_family"], "Arial")
        self.assertEqual(h1["line_spacing"], 115)
        self.assertEqual(h1["font_size_pt"], 22)
        self.assertTrue(h1["bold"])

    def test_every_named_style_is_fully_specified(self):
        for t in style_lint.NAMED_STYLE_TYPES:
            s = style_lint.resolved_named_style(SPEC, t)
            for k in ("font_family", "font_size_pt", "bold", "line_spacing", "space_above_pt", "space_below_pt"):
                self.assertIsNotNone(s.get(k), f"{t}.{k}")


class TestCleanDocPasses(unittest.TestCase):
    def test_template_shaped_doc_has_no_violations(self):
        r = style_lint.lint_document(jam_doc(), SPEC)
        self.assertEqual(r["violations"], [], json.dumps(r, indent=1))
        self.assertTrue(r["ok"])
        self.assertEqual(r["errors"], 0)
        self.assertEqual(r["warnings"], 0)

    def test_explicit_overrides_equal_to_spec_are_fine(self):
        d = jam_doc()
        d["tabs"][0]["documentTab"]["body"]["content"][2]["paragraph"]["paragraphStyle"].update(
            {"lineSpacing": 115, "spaceAbove": pt(18), "spaceBelow": pt(6)})
        self.assertTrue(style_lint.lint_document(d, SPEC)["ok"])


class TestNamedStyles(unittest.TestCase):
    def test_wrong_doc_named_style_is_flagged_once_and_leaks_into_paragraphs(self):
        named = jam_named_styles()
        named["styles"][0]["textStyle"]["fontSize"] = pt(11)
        r = style_lint.lint_document(doc([para("prose")], named=named), SPEC)
        self.assertFalse(r["ok"])
        self.assertIn("named_style.font_size", rules(r))
        self.assertIn("run.font_size", rules(r))

    def test_missing_named_style_values_fall_back_to_docs_defaults(self):
        named = {"styles": [{"namedStyleType": "NORMAL_TEXT", "textStyle": {}, "paragraphStyle": {}}]}
        r = style_lint.lint_document(doc([para("prose")], named=named), SPEC)
        self.assertIn("paragraph.line_spacing", rules(r))  # Docs default 100 != 115


class TestParagraphRhythm(unittest.TestCase):
    def test_house_1768_rhythm_on_a_heading_is_flagged(self):
        d = doc([para("Heading", "HEADING_2", ps={"lineSpacing": 100, "spaceAbove": pt(0), "spaceBelow": pt(0)})])
        r = rules(style_lint.lint_document(d, SPEC), "error")
        self.assertTrue({"paragraph.line_spacing", "paragraph.space_above", "paragraph.space_below"} <= r)


class TestRuns(unittest.TestCase):
    def test_body_font_size_override(self):
        d = doc([para("x", runs=[("small\n", {"fontSize": pt(11)})])])
        self.assertIn("run.font_size", rules(style_lint.lint_document(d, SPEC)))

    def test_foreign_font_family(self):
        d = doc([para("x", runs=[("mono\n", {"weightedFontFamily": {"fontFamily": "Times New Roman"}})])])
        self.assertIn("run.font_family", rules(style_lint.lint_document(d, SPEC)))

    def test_native_code_block_font_is_allowed(self):
        d = doc([para("x", runs=[("code\n", {"weightedFontFamily": {"fontFamily": "Roboto Mono"}})])])
        self.assertTrue(style_lint.lint_document(d, SPEC)["ok"])

    def test_code_font_is_allowed_but_size_still_checked(self):
        code = {"weightedFontFamily": {"fontFamily": "Courier New"}}
        ok = doc([para("x", runs=[("code\n", code)])])
        self.assertTrue(style_lint.lint_document(ok, SPEC)["ok"])
        bad = doc([para("x", runs=[("code\n", dict(code, fontSize=pt(9)))])])
        self.assertIn("run.font_size", rules(style_lint.lint_document(bad, SPEC)))

    def test_unbolded_heading_run(self):
        d = doc([para("H", "HEADING_2", runs=[("Heading\n", {"bold": False})])])
        self.assertIn("run.bold", rules(style_lint.lint_document(d, SPEC)))

    def test_body_bold_is_emphasis_not_a_violation(self):
        d = doc([para("x", runs=[("strong\n", {"bold": True})])])
        self.assertTrue(style_lint.lint_document(d, SPEC)["ok"])

    def test_grey_heading_color(self):
        d = doc([para("H4", "HEADING_4", runs=[("Minor\n", {"foregroundColor": {"color": {"rgbColor": {}}}})])])
        self.assertIn("run.color", rules(style_lint.lint_document(d, SPEC)))


class TestLists(unittest.TestCase):
    def test_non_dash_glyph_is_a_warning_only(self):
        lists = {"L1": {"listProperties": {"nestingLevels": [
            {"glyphSymbol": "➔", "indentStart": pt(36), "indentFirstLine": pt(18)}]}}}
        r = style_lint.lint_document(doc([item("a")], lists=lists), SPEC)
        self.assertEqual(rules(r, "warning"), {"list.glyph"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["warnings"], 1)

    def test_ordered_lists_skip_the_glyph_rule(self):
        lists = {"L1": {"listProperties": {"nestingLevels": [
            {"glyphType": "DECIMAL", "glyphFormat": "%0.", "indentStart": pt(36), "indentFirstLine": pt(18)}]}}}
        self.assertTrue(style_lint.lint_document(doc([item("a")], lists=lists), SPEC)["ok"])

    def test_indent_off_the_ladder(self):
        d = doc([item("a", ps={"indentStart": pt(40), "indentFirstLine": pt(22)})])
        self.assertIn("list.indent", rules(style_lint.lint_document(d, SPEC)))

    def test_depth_via_indent_alone_is_fine(self):
        # #1770: nesting level is cosmetic for dash lists; depth may come from indents only.
        d = doc([item("a", level=0, ps={"indentStart": pt(72), "indentFirstLine": pt(54)})])
        self.assertTrue(style_lint.lint_document(d, SPEC)["ok"])

    def test_wrong_hanging_indent(self):
        d = doc([item("a", ps={"indentFirstLine": pt(36)})])
        self.assertIn("list.indent", rules(style_lint.lint_document(d, SPEC)))


class TestBlankParagraphs(unittest.TestCase):
    def test_two_consecutive_blanks(self):
        d = doc([para("a"), para(""), para(""), para("b")])
        self.assertIn("blank.consecutive", rules(style_lint.lint_document(d, SPEC)))

    def test_blank_next_to_heading(self):
        for content in ([para(""), para("H", "HEADING_2"), para("a")],
                        [para("H", "HEADING_2"), para(""), para("a")]):
            self.assertIn("blank.adjacent_heading", rules(style_lint.lint_document(doc(content), SPEC)))

    def test_tab_end_anchor_is_ignored(self):
        # doc() always appends a blank anchor; a heading right before it must not trip the rule.
        self.assertTrue(style_lint.lint_document(doc([para("a"), para("H", "HEADING_2")]), SPEC)["ok"])


class TestTables(unittest.TestCase):
    def test_top_aligned_cells(self):
        d = doc([table([["A", "B"], ["a", "b"]], align="TOP")])
        self.assertIn("table.cell_alignment", rules(style_lint.lint_document(d, SPEC)))

    def test_unbold_header(self):
        d = doc([table([["A", "B"], ["a", "b"]], header_bold=False)])
        self.assertIn("table.header_bold", rules(style_lint.lint_document(d, SPEC)))

    def test_overflowing_width(self):
        d = doc([table([["A", "B", "C"], ["a", "b", "c"]], widths=(175, 175, 175))])
        self.assertIn("table.width", rules(style_lint.lint_document(d, SPEC)))

    def test_evenly_distributed_columns_count_as_full_width(self):
        d = doc([table([["A", "B"], ["a", "b"]])])
        for c in d["tabs"][0]["documentTab"]["body"]["content"][1]["table"]["tableStyle"]["tableColumnProperties"]:
            c.clear()
            c["widthType"] = "EVENLY_DISTRIBUTED"
        self.assertTrue(style_lint.lint_document(d, SPEC)["ok"])

    def test_cell_paragraph_rhythm_is_checked(self):
        d = doc([table([["A", "B"], ["a", "b"]], cell_ps={"lineSpacing": 100})])
        self.assertIn("paragraph.line_spacing", rules(style_lint.lint_document(d, SPEC)))


class TestPage(unittest.TestCase):
    def test_margins(self):
        ds = {"pageSize": {"width": pt(612), "height": pt(792)}, "marginLeft": pt(36)}
        d = doc([para("a")], doc_style=ds)
        self.assertIn("page.margin", rules(style_lint.lint_document(d, SPEC)))


class TestTabsAndOutput(unittest.TestCase):
    def test_child_tabs_are_walked_and_tab_filter_applies(self):
        child = doc([para("x", runs=[("small\n", {"fontSize": pt(9)})])], tab_id="t.child", title="Child")["tabs"][0]
        d = doc([para("fine")], child_tabs=[child])
        self.assertFalse(style_lint.lint_document(d, SPEC)["ok"])
        self.assertTrue(style_lint.lint_document(d, SPEC, tab_id="t.0")["ok"])
        r = style_lint.lint_document(d, SPEC, tab_id="t.child")
        self.assertFalse(r["ok"])
        self.assertEqual(r["checked"]["tabs"], 1)

    def test_unknown_tab_id_raises(self):
        with self.assertRaises(ValueError):
            style_lint.lint_document(jam_doc(), SPEC, tab_id="t.nope")

    def test_violations_are_grouped_capped_and_content_free(self):
        long_text = "x" * 500
        d = doc([para(long_text, runs=[(long_text + "\n", {"fontSize": pt(9)})]) for _ in range(40)])
        r = style_lint.lint_document(d, SPEC)
        group = next(v for v in r["violations"] if v["rule"] == "run.font_size")
        self.assertEqual(group["count"], 40)
        self.assertLessEqual(len(group["samples"]), style_lint.MAX_SAMPLES)
        self.assertLess(len(json.dumps(r)), 3000)  # never echoes content
        self.assertNotIn("x" * 40, json.dumps(r))

    def test_real_world_sized_output_stays_small(self):
        # Many distinct groups: output is still bounded, and by_rule keeps the totals.
        content = [para("x", runs=[("s\n", {"fontSize": pt(5 + i)})]) for i in range(30)]
        r = style_lint.lint_document(doc(content), SPEC)
        self.assertLessEqual(len(r["violations"]), style_lint.MAX_GROUPS)
        self.assertEqual(r["by_rule"]["run.font_size"], 29)  # 13pt is the one correct size
        self.assertEqual(r["truncated_groups"], 29 - style_lint.MAX_GROUPS)
        self.assertLess(len(json.dumps(r, ensure_ascii=False)), 4000)

    def test_errors_sort_before_warnings(self):
        lists = {"L1": {"listProperties": {"nestingLevels": [
            {"glyphSymbol": "●", "indentStart": pt(36), "indentFirstLine": pt(18)}]}}}
        d = doc([item("a"), para("x", runs=[("s\n", {"fontSize": pt(9)})])], lists=lists)
        sev = [v["severity"] for v in style_lint.lint_document(d, SPEC)["violations"]]
        self.assertEqual(sev, sorted(sev, key=lambda s: s != "error"))

    def test_input_is_not_mutated(self):
        d = jam_doc()
        before = copy.deepcopy(d)
        style_lint.lint_document(d, SPEC)
        self.assertEqual(d, before)


class TestGdocsLintTool(unittest.TestCase):
    """The MCP tool: fetch with includeTabsContent, lint, return compact JSON."""

    def _call(self, payload, **kw):
        from unittest.mock import patch
        import mcp_server
        with patch("auth.api", return_value=payload) as api:
            out = json.loads(mcp_server.gdocs_lint("DOC", **kw))
        return out, api

    def test_clean_doc(self):
        out, api = self._call(jam_doc())
        self.assertTrue(out["ok"])
        self.assertEqual(out["documentId"], "DOC")
        method, url = api.call_args[0][:2]
        self.assertEqual(method, "GET")
        self.assertIn("includeTabsContent=true", url)

    def test_api_error_passes_through(self):
        out, _ = self._call({"error": {"code": 404, "message": "nope"}})
        self.assertEqual(out["error"]["code"], 404)

    def test_bad_tab_is_an_error_not_a_crash(self):
        out, _ = self._call(jam_doc(), tab_id="t.nope")
        self.assertIn("tab not found", out["error"])

    def test_is_registered_as_a_tool(self):
        import asyncio
        import mcp_server
        tools = asyncio.run(mcp_server.mcp.list_tools())
        self.assertIn("gdocs_lint", {t.name for t in tools})


if __name__ == "__main__":
    unittest.main()
