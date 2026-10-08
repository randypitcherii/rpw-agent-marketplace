#!/usr/bin/env python3
"""Tests for style_normalize (#2001): pure documents.get → batchUpdate request builder.

Payloads are synthetic (built with test_style_lint's helpers) and given real,
sequential Docs indices so every request range can be asserted.
"""

import unittest

import style_normalize
from test_style_lint import SPEC, doc, item, jam_doc, jam_named_styles, para, pt, table


def _u16(s):
    return len(s.encode("utf-16-le")) // 2


def indexed(d):
    """Assign startIndex/endIndex the way Docs does (sectionBreak, paragraphs, tables)."""
    for tab in d["tabs"]:
        pos = 0
        for el in tab["documentTab"]["body"]["content"]:
            pos = _index_block(el, pos)
    return d


def _index_block(el, pos):
    el["startIndex"] = pos
    if "sectionBreak" in el:
        pos += 1
    elif "paragraph" in el:
        for e in el["paragraph"]["elements"]:
            e["startIndex"] = pos
            pos += _u16(e["textRun"]["content"])
            e["endIndex"] = pos
    elif "table" in el:
        pos += 1
        for row in el["table"]["tableRows"]:
            pos += 1
            for cell in row["tableCells"]:
                pos += 1
                for c in cell["content"]:
                    pos = _index_block(c, pos)
        pos += 1
    el["endIndex"] = pos
    return pos


def reqs(d, **kw):
    return style_normalize.normalize_requests(indexed(d), SPEC, **kw)


def kinds(rs):
    return [next(iter(r)) for r in rs]


def body(d):
    return d["tabs"][0]["documentTab"]["body"]["content"]


class TestCleanDoc(unittest.TestCase):
    def test_template_shaped_doc_needs_nothing(self):
        self.assertEqual(reqs(jam_doc()), [])


class TestNamedStyles(unittest.TestCase):
    def test_only_the_wrong_named_style_is_pinned(self):
        named = jam_named_styles()
        named["styles"][2]["textStyle"]["fontSize"] = pt(14)  # HEADING_2
        rs = reqs(doc([para("H", "HEADING_2")], named=named))
        self.assertEqual(kinds(rs), ["updateNamedStyle"])
        u = rs[0]["updateNamedStyle"]
        self.assertEqual(u["tabId"], "t.0")
        self.assertEqual(u["namedStyle"]["namedStyleType"], "HEADING_2")
        self.assertEqual(u["namedStyle"]["textStyle"]["fontSize"], pt(18))
        self.assertEqual(u["namedStyle"]["textStyle"]["weightedFontFamily"], {"fontFamily": "Arial"})
        self.assertEqual(u["namedStyle"]["paragraphStyle"]["spaceAbove"], pt(18))
        self.assertIn("textStyle.fontSize", u["fields"])
        self.assertIn("paragraphStyle.lineSpacing", u["fields"])

    def test_docs_default_named_styles_are_all_pinned(self):
        named = {"styles": [{"namedStyleType": "NORMAL_TEXT", "textStyle": {"fontSize": pt(11)},
                             "paragraphStyle": {"lineSpacing": 115}}]}
        rs = reqs(doc([para("prose")], named=named))
        pinned = [r["updateNamedStyle"]["namedStyle"]["namedStyleType"] for r in rs if "updateNamedStyle" in r]
        self.assertEqual(set(pinned), set(style_normalize.NAMED_STYLE_TYPES))
        # The paragraph has no override, so pinning the named styles is the whole fix.
        self.assertEqual(set(kinds(rs)), {"updateNamedStyle"})

    def test_grey_headings_get_their_colour(self):
        s = style_normalize.spec_named_style(SPEC, "HEADING_4")
        rgb = s["textStyle"]["foregroundColor"]["color"]["rgbColor"]
        self.assertAlmostEqual(rgb["red"], 0.4, places=2)
        self.assertNotIn("foregroundColor", style_normalize.spec_named_style(SPEC, "HEADING_1")["textStyle"])


class TestOverrides(unittest.TestCase):
    def test_1768_rhythm_on_a_heading_is_reset_to_inherit(self):
        d = doc([para("Heading", "HEADING_2", ps={"lineSpacing": 100, "spaceAbove": pt(0), "spaceBelow": pt(0)})])
        rs = reqs(d)
        self.assertEqual(kinds(rs), ["updateParagraphStyle"])
        u = rs[0]["updateParagraphStyle"]
        self.assertEqual(u["paragraphStyle"], {})
        self.assertEqual(set(u["fields"].split(",")), {"lineSpacing", "spaceAbove", "spaceBelow"})
        h = body(d)[1]
        self.assertEqual(u["range"], {"startIndex": h["startIndex"], "endIndex": h["endIndex"], "tabId": "t.0"})

    def test_run_overrides_are_reset_and_code_font_is_kept(self):
        d = doc([para("x", runs=[("small ", {"fontSize": pt(9)}),
                                 ("serif ", {"weightedFontFamily": {"fontFamily": "Georgia"}}),
                                 ("code\n", {"weightedFontFamily": {"fontFamily": "Courier New"}})])])
        rs = reqs(d)
        self.assertEqual(kinds(rs), ["updateTextStyle", "updateTextStyle"])
        by_field = {r["updateTextStyle"]["fields"]: r["updateTextStyle"] for r in rs}
        self.assertEqual(set(by_field), {"fontSize", "weightedFontFamily"})
        runs = body(d)[1]["paragraph"]["elements"]
        self.assertEqual(by_field["fontSize"]["range"]["startIndex"], runs[0]["startIndex"])
        self.assertEqual(by_field["weightedFontFamily"]["range"]["startIndex"], runs[1]["startIndex"])
        self.assertTrue(all(r["updateTextStyle"]["textStyle"] == {} for r in rs))

    def test_one_run_with_two_bad_fields_is_one_request(self):
        d = doc([para("x", runs=[("both\n", {"fontSize": pt(9), "weightedFontFamily": {"fontFamily": "Georgia"}})])])
        rs = reqs(d)
        self.assertEqual(len(rs), 1)
        self.assertEqual(set(rs[0]["updateTextStyle"]["fields"].split(",")), {"fontSize", "weightedFontFamily"})

    def test_list_indent_is_set_explicitly(self):
        rs = reqs(doc([item("a", ps={"indentStart": pt(40), "indentFirstLine": pt(22)})]))
        self.assertEqual(kinds(rs), ["updateParagraphStyle"])
        ps = rs[0]["updateParagraphStyle"]["paragraphStyle"]
        self.assertEqual((ps["indentStart"], ps["indentFirstLine"]), (pt(36), pt(18)))

    def test_non_dash_glyph_produces_no_request(self):
        lists = {"L1": {"listProperties": {"nestingLevels": [
            {"glyphSymbol": "➔", "indentStart": pt(36), "indentFirstLine": pt(18)}]}}}
        self.assertEqual(reqs(doc([item("a")], lists=lists)), [])


class TestTables(unittest.TestCase):
    def test_alignment_width_and_header_bold(self):
        d = doc([table([["A", "B", "C"], ["a", "b", "c"]], widths=(175, 175, 175), align="TOP", header_bold=False)])
        rs = reqs(d)
        self.assertEqual(kinds(rs).count("updateTableCellStyle"), 1)  # one request for the whole grid
        cell = next(r["updateTableCellStyle"] for r in rs if "updateTableCellStyle" in r)
        tstart = body(d)[1]["startIndex"]
        self.assertEqual(cell["tableRange"]["tableCellLocation"]["tableStartLocation"], {"index": tstart, "tabId": "t.0"})
        self.assertEqual((cell["tableRange"]["rowSpan"], cell["tableRange"]["columnSpan"]), (2, 3))
        width = next(r["updateTableColumnProperties"] for r in rs if "updateTableColumnProperties" in r)
        self.assertEqual(width["columnIndices"], [0, 1, 2])
        self.assertEqual(width["tableColumnProperties"]["width"], pt(156))
        bolds = [r for r in rs if "updateTextStyle" in r and r["updateTextStyle"]["textStyle"] == {"bold": True}]
        self.assertEqual(len(bolds), 3)


class TestBlankParagraphs(unittest.TestCase):
    def _deleted(self, d, rs):
        spans = [(r["deleteContentRange"]["range"]["startIndex"], r["deleteContentRange"]["range"]["endIndex"])
                 for r in rs if "deleteContentRange" in r]
        return spans

    def test_consecutive_blanks_keep_one(self):
        d = doc([para("a"), para(""), para(""), para(""), para("b")])
        rs = reqs(d)
        b = body(d)
        self.assertEqual(self._deleted(d, rs), [(b[4]["startIndex"], b[4]["endIndex"]),
                                                (b[3]["startIndex"], b[3]["endIndex"])])

    def test_blanks_next_to_headings_go(self):
        d = doc([para("a"), para(""), para("H", "HEADING_2"), para(""), para("b")])
        b = body(d)
        rs = reqs(d)
        self.assertEqual(self._deleted(d, rs), [(b[4]["startIndex"], b[4]["endIndex"]),
                                                (b[2]["startIndex"], b[2]["endIndex"])])

    def test_the_paragraph_before_a_table_is_never_deleted(self):
        d = doc([para("a"), para(""), para(""), table([["A", "B"], ["a", "b"]])])
        b = body(d)
        rs = reqs(d)
        # Two blanks before the table: keep the required one (b[3]), delete b[2].
        self.assertEqual(self._deleted(d, rs), [(b[2]["startIndex"], b[2]["endIndex"])])

    def test_heading_over_a_table_merges_onto_the_required_paragraph(self):
        d = doc([para("H", "HEADING_2"), para(""), table([["A", "B"], ["a", "b"]])])
        h = body(d)[1]
        rs = reqs(d)
        self.assertEqual(self._deleted(d, rs), [(h["endIndex"] - 1, h["endIndex"])])
        i = kinds(rs).index("deleteContentRange")
        restyle = rs[i + 1]["updateParagraphStyle"]
        self.assertEqual(restyle["paragraphStyle"], {"namedStyleType": "HEADING_2"})
        self.assertEqual((restyle["range"]["startIndex"], restyle["range"]["endIndex"]),
                         (h["startIndex"], h["endIndex"]))

    def test_tab_end_anchor_is_kept(self):
        self.assertEqual(reqs(doc([para("a"), para("H", "HEADING_2")])), [])

    def test_deletions_run_last_and_highest_index_first(self):
        d = doc([para("H", "HEADING_2", ps={"lineSpacing": 100}), para(""), para("a"),
                 para(""), para(""), para("b", runs=[("b\n", {"fontSize": pt(9)})])])
        ks = kinds(reqs(d))
        first_delete = ks.index("deleteContentRange")
        self.assertTrue(all(k == "deleteContentRange" for k in ks[first_delete:]))
        starts = [r["deleteContentRange"]["range"]["startIndex"] for r in reqs(d) if "deleteContentRange" in r]
        self.assertEqual(starts, sorted(starts, reverse=True))


class TestPageAndScope(unittest.TestCase):
    def test_page_margins(self):
        ds = {"pageSize": {"width": pt(612), "height": pt(792)}, "marginLeft": pt(36)}
        rs = reqs(doc([para("a")], doc_style=ds))
        self.assertEqual(kinds(rs), ["updateDocumentStyle"])
        u = rs[0]["updateDocumentStyle"]
        self.assertEqual(u["tabId"], "t.0")
        self.assertEqual(u["documentStyle"]["marginLeft"], pt(72))

    def test_tab_scope(self):
        child = doc([para("x", runs=[("small\n", {"fontSize": pt(9)})])], tab_id="t.c", title="Child")["tabs"][0]
        d = doc([para("fine")], child_tabs=[child])
        indexed({"tabs": [child]})
        self.assertEqual(reqs(d, tab_id="t.0"), [])
        rs = reqs(d, tab_id="t.c")
        self.assertEqual(rs[0]["updateTextStyle"]["range"]["tabId"], "t.c")
        with self.assertRaises(ValueError):
            reqs(d, tab_id="t.missing")


if __name__ == "__main__":
    unittest.main()
