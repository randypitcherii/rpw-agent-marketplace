#!/usr/bin/env python3
"""Tests for style_gate (#2001): normalize + lint after every content write tool.

The Docs API is faked: GETs return scripted documents.get payloads, POSTs are recorded.
"""

import json
import os
import unittest
from unittest.mock import patch

import mcp_server
import style_gate
from test_style_lint import doc, jam_doc, para, pt
from test_style_normalize import indexed


class FakeApi:
    """GET → the next scripted payload (the last one repeats); POST → recorded reply."""

    def __init__(self, gets, post_reply=None):
        self.gets = list(gets)
        self.posts = []
        self.post_reply = post_reply if post_reply is not None else {"replies": []}

    def __call__(self, method, url, data=None):
        if method == "GET":
            return self.gets.pop(0) if len(self.gets) > 1 else self.gets[0]
        self.posts.append(data["requests"])
        return self.post_reply


def dirty(n_paragraphs=1):
    return indexed(doc([para(f"p{i}", runs=[(f"p{i}\n", {"fontSize": pt(9)})]) for i in range(n_paragraphs)]))


class TestApply(unittest.TestCase):
    def test_clean_tab_sends_nothing(self):
        api = FakeApi([indexed(jam_doc())])
        with patch("auth.api", side_effect=api):
            out = style_gate.apply("DOC", "t.0")
        self.assertEqual(api.posts, [])
        self.assertTrue(out["ok"])
        self.assertEqual(out["normalized"], 0)
        self.assertEqual(out["tabId"], "t.0")

    def test_dirty_tab_is_normalized_then_relinted(self):
        api = FakeApi([dirty(), indexed(jam_doc())])
        with patch("auth.api", side_effect=api):
            out = style_gate.apply("DOC", "t.0")
        self.assertEqual(len(api.posts), 1)
        self.assertEqual(next(iter(api.posts[0][0])), "updateTextStyle")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["normalized"], 1)

    def test_default_tab_is_the_first(self):
        api = FakeApi([indexed(jam_doc())])
        with patch("auth.api", side_effect=api):
            self.assertEqual(style_gate.apply("DOC")["tabId"], "t.0")

    def test_requests_are_batched_in_order(self):
        api = FakeApi([dirty(120), indexed(jam_doc())])
        with patch("auth.api", side_effect=api):
            out = style_gate.apply("DOC", "t.0")
        self.assertEqual([len(b) for b in api.posts], [50, 50, 20])
        starts = [r["updateTextStyle"]["range"]["startIndex"] for b in api.posts for r in b]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(out["normalized"], 120)

    def test_api_failure_is_reported_not_raised(self):
        api = FakeApi([dirty()], post_reply={"error": {"code": 400, "message": "bad request"}})
        with patch("auth.api", side_effect=api):
            out = style_gate.apply("DOC", "t.0")
        self.assertFalse(out["ok"])
        self.assertIn("bad request", out["error"])
        self.assertEqual(out["batchesCompleted"], 0)

    def test_errors_that_survive_normalize_fail_the_gate(self):
        api = FakeApi([dirty(), dirty()])  # the re-read is still off-style
        with patch("auth.api", side_effect=api):
            out = style_gate.gate({"status": "written", "documentId": "DOC"}, "DOC", "t.0")
        self.assertEqual(out["status"], "written_but_style_check_failed")
        self.assertIn("house-style error", out["error"])
        self.assertFalse(out["style"]["ok"])
        self.assertLessEqual(len(out["style"]["samples"]), style_gate.SUMMARY_SAMPLES)

    def test_summary_is_small(self):
        api = FakeApi([dirty(200), dirty(200)])
        with patch("auth.api", side_effect=api):
            out = style_gate.gate({"status": "written"}, "DOC", "t.0")
        self.assertLess(len(json.dumps(out, ensure_ascii=False)), 2500)


class TestToolWiring(unittest.TestCase):
    """Each content write tool gates only its successful status, on the tab it wrote."""

    STYLE_OK = {"ok": True, "errors": 0, "warnings": 0, "by_rule": {}, "samples": [], "tabId": "t", "normalized": 3}

    def setUp(self):
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)
        self._audit = patch("policy.append_audit")
        self._audit.start()
        self._gate_doc = patch("policy.gate_write", return_value=None)
        self._gate_doc.start()

    def tearDown(self):
        self._audit.stop()
        self._gate_doc.stop()

    def _run(self, target, ret, call):
        with patch(target, return_value=ret), \
             patch("style_gate.apply", return_value=dict(self.STYLE_OK)) as apply:
            out = json.loads(call())
        return out, apply

    def test_write_to_tab(self):
        out, apply = self._run("mcp_server._write_to_tab", {"status": "written", "documentId": "D", "tabId": "t.1"},
                               lambda: mcp_server.gdocs_write_to_tab("D", "t.1", "x"))
        apply.assert_called_once_with("D", "t.1")
        self.assertEqual(out["status"], "written")
        self.assertTrue(out["style"]["ok"])

    def test_add_tab_gates_the_new_tab(self):
        out, apply = self._run("mcp_server.add_tab", {"status": "tab_added", "documentId": "D", "tabId": "t.new"},
                               lambda: mcp_server.gdocs_add_tab("D", "New", "x"))
        apply.assert_called_once_with("D", "t.new")
        self.assertIn("style", out)

    def test_create_gates_the_first_tab(self):
        out, apply = self._run("mcp_server.create_doc", {"status": "created", "documentId": "D"},
                               lambda: mcp_server.gdocs_create("T", "x"))
        apply.assert_called_once_with("D", None)

    def test_update_gates_the_first_tab(self):
        out, apply = self._run("mcp_server.update_doc", {"status": "updated", "documentId": "D"},
                               lambda: mcp_server.gdocs_update("D", "x"))
        apply.assert_called_once_with("D", None)

    def test_failed_writes_are_not_gated(self):
        for target, ret, call in (
            ("mcp_server._write_to_tab", {"status": "cleared_but_write_failed", "error": "e"},
             lambda: mcp_server.gdocs_write_to_tab("D", "t", "x")),
            ("mcp_server.create_doc", {"status": "created_but_move_failed", "documentId": "D", "error": "e"},
             lambda: mcp_server.gdocs_create("T", "x")),
            ("mcp_server.add_tab", {"status": "tab_added_but_content_failed", "tabId": "t", "error": "e"},
             lambda: mcp_server.gdocs_add_tab("D", "N", "x")),
            ("mcp_server.update_doc", {"status": "update_failed", "error": "e"},
             lambda: mcp_server.gdocs_update("D", "x")),
        ):
            out, apply = self._run(target, ret, call)
            apply.assert_not_called()
            self.assertNotIn("style", out)

    def test_find_replace_is_not_gated(self):
        out, apply = self._run("mcp_server._find_replace", {"status": "replaced", "documentId": "D"},
                               lambda: mcp_server.gdocs_find_replace("D", "a", "b"))
        apply.assert_not_called()

    def test_style_failure_becomes_an_error_result(self):
        bad = dict(self.STYLE_OK, ok=False, errors=4, samples=["run.font_size (error): expected 13, got 9 ×4 @ x"])
        with patch("mcp_server._write_to_tab", return_value={"status": "written", "documentId": "D"}), \
             patch("style_gate.apply", return_value=bad):
            out = json.loads(mcp_server.gdocs_write_to_tab("D", "t", "x"))
        self.assertEqual(out["status"], "written_but_style_check_failed")
        self.assertIn("4 house-style error", out["error"])


if __name__ == "__main__":
    unittest.main()
