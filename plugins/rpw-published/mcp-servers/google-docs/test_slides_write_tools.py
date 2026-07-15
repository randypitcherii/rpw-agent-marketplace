#!/usr/bin/env python3
"""
Unit tests for the Google Slides template-fill tools in ``tools_slides.py`` (#196).

Fully mocked — no live Google API calls. The tools call the single ``policy.api``
entry point, so each test patches ``policy.api`` and asserts the HTTP method, URL
(endpoint + query params), and request body the tool shaped — the same pattern
the Sheets suite (``test_google_sheets_mcp.py``) and the existing Slides suite
(``test_slides_tools.py``) use. Gating tests drive the read-only / allow-list
paths through ``policy``.

Tools registered via ``@mcp.tool`` remain callable as plain module functions on
``tools_slides`` (mirroring how the other suites invoke their tools).
"""

import json
import os
import unittest
from unittest.mock import patch

import tools_slides


class _GatedWriteBase(unittest.TestCase):
    """Shared read-only / allow-list env setup for the write-tool tests."""

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]


class TestCopyTemplate(_GatedWriteBase):
    """gdocs_slides_copy_template shapes a gated Drive files.copy POST."""

    def test_happy_path_body_and_url(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"id": "new_pid", "name": "Acme QBR", "parents": ["fold"]}
            result = tools_slides.gdocs_slides_copy_template("tmpl", "Acme QBR", folder_id="fold")

        data = json.loads(result)
        self.assertEqual(data["status"], "copied")
        self.assertEqual(data["presentationId"], "new_pid")
        self.assertEqual(data["url"], "https://docs.google.com/presentation/d/new_pid/edit")
        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            url,
            "https://www.googleapis.com/drive/v3/files/tmpl/copy?fields=id,name,parents",
        )
        self.assertEqual(body, {"name": "Acme QBR", "parents": ["fold"]})
        mock_audit.assert_called_once()

    def test_no_folder_omits_parents(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"id": "new_pid"}
            tools_slides.gdocs_slides_copy_template("tmpl", "Acme QBR")
        body = mock_api.call_args[0][2]
        self.assertEqual(body, {"name": "Acme QBR"})
        self.assertNotIn("parents", body)

    def test_normalizes_template_url(self):
        url = "https://docs.google.com/presentation/d/TMPL99/edit"
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"id": "new_pid"}
            tools_slides.gdocs_slides_copy_template(url, "Deck")
        called = mock_api.call_args[0][1]
        self.assertTrue(called.startswith("https://www.googleapis.com/drive/v3/files/TMPL99/copy"))

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            result = tools_slides.gdocs_slides_copy_template("tmpl", "Deck")
        self.assertIn("Read-only", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_folder_not_in_allow_list_blocks(self):
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "allowed"
        with patch("policy.api") as mock_api:
            result = tools_slides.gdocs_slides_copy_template("tmpl", "Deck", folder_id="other")
        self.assertIn("not in allow-list", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_error_envelope_passed_through_no_audit(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 404, "message": "no such file"}}
            result = tools_slides.gdocs_slides_copy_template("tmpl", "Deck")
        self.assertIn("error", json.loads(result))
        mock_audit.assert_not_called()

    def test_catches_exception(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("net down")
            result = tools_slides.gdocs_slides_copy_template("tmpl", "Deck")
        self.assertIn("net down", json.loads(result)["error"])


class TestReplaceAllText(_GatedWriteBase):
    """gdocs_slides_replace_all_text shapes a gated multi-replaceAllText batchUpdate."""

    def test_happy_path_one_request_per_key(self):
        mapping = {"{{account}}": "Acme", "{{quarter}}": "Q3"}
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"replies": [{}, {}]}
            result = tools_slides.gdocs_slides_replace_all_text("pid", mapping)

        self.assertNotIn("error", json.loads(result))
        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://slides.googleapis.com/v1/presentations/pid:batchUpdate")
        reqs = body["requests"]
        self.assertEqual(len(reqs), 2)
        found = {r["replaceAllText"]["containsText"]["text"]: r["replaceAllText"]["replaceText"] for r in reqs}
        self.assertEqual(found, {"{{account}}": "Acme", "{{quarter}}": "Q3"})
        self.assertFalse(reqs[0]["replaceAllText"]["containsText"]["matchCase"])
        mock_audit.assert_called_once()

    def test_match_case_and_value_coercion(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            tools_slides.gdocs_slides_replace_all_text("pid", {"{{n}}": 42}, match_case=True)
        req = mock_api.call_args[0][2]["requests"][0]["replaceAllText"]
        self.assertEqual(req["replaceText"], "42")
        self.assertTrue(req["containsText"]["matchCase"])

    def test_empty_mapping_rejected(self):
        with patch("policy.api") as mock_api:
            result = tools_slides.gdocs_slides_replace_all_text("pid", {})
        self.assertIn("empty", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_normalizes_url(self):
        url = "https://docs.google.com/presentation/d/pid/edit"
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            tools_slides.gdocs_slides_replace_all_text(url, {"a": "b"})
        self.assertEqual(
            mock_api.call_args[0][1],
            "https://slides.googleapis.com/v1/presentations/pid:batchUpdate",
        )

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            result = tools_slides.gdocs_slides_replace_all_text("pid", {"a": "b"})
        self.assertIn("Read-only", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_error_envelope_passed_through_no_audit(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 403, "message": "denied"}}
            result = tools_slides.gdocs_slides_replace_all_text("pid", {"a": "b"})
        self.assertIn("error", json.loads(result))
        mock_audit.assert_not_called()

    def test_catches_exception(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("boom")
            result = tools_slides.gdocs_slides_replace_all_text("pid", {"a": "b"})
        self.assertIn("boom", json.loads(result)["error"])


class TestFillTable(_GatedWriteBase):
    """gdocs_slides_fill_table shapes gated insertText (and optional deleteText) requests."""

    def test_happy_path_insert_only(self):
        cells = [
            {"row": 0, "column": 0, "text": "Metric"},
            {"row": 1, "column": 1, "text": "$1.2M"},
        ]
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"replies": [{}, {}]}
            result = tools_slides.gdocs_slides_fill_table("pid", "tbl", cells)

        self.assertNotIn("error", json.loads(result))
        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://slides.googleapis.com/v1/presentations/pid:batchUpdate")
        reqs = body["requests"]
        self.assertEqual(len(reqs), 2)
        self.assertEqual(
            reqs[0]["insertText"],
            {
                "objectId": "tbl",
                "cellLocation": {"rowIndex": 0, "columnIndex": 0},
                "text": "Metric",
                "insertionIndex": 0,
            },
        )
        self.assertEqual(reqs[1]["insertText"]["cellLocation"], {"rowIndex": 1, "columnIndex": 1})
        mock_audit.assert_called_once()

    def test_clear_existing_prepends_delete(self):
        cells = [{"row": 2, "column": 3, "text": "new"}]
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}, {}]}
            tools_slides.gdocs_slides_fill_table("pid", "tbl", cells, clear_existing=True)
        reqs = mock_api.call_args[0][2]["requests"]
        self.assertEqual(len(reqs), 2)
        self.assertEqual(
            reqs[0]["deleteText"],
            {
                "objectId": "tbl",
                "cellLocation": {"rowIndex": 2, "columnIndex": 3},
                "textRange": {"type": "ALL"},
            },
        )
        self.assertIn("insertText", reqs[1])

    def test_text_coerced_to_string(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            tools_slides.gdocs_slides_fill_table("pid", "tbl", [{"row": 0, "column": 0, "text": 7}])
        self.assertEqual(mock_api.call_args[0][2]["requests"][0]["insertText"]["text"], "7")

    def test_empty_cells_rejected(self):
        with patch("policy.api") as mock_api:
            result = tools_slides.gdocs_slides_fill_table("pid", "tbl", [])
        self.assertIn("empty", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_missing_cell_key_reported(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            result = tools_slides.gdocs_slides_fill_table("pid", "tbl", [{"row": 0, "text": "x"}])
        self.assertIn("missing required key", json.loads(result)["error"])

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            result = tools_slides.gdocs_slides_fill_table("pid", "tbl", [{"row": 0, "column": 0, "text": "x"}])
        self.assertIn("Read-only", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_error_envelope_passed_through_no_audit(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 400, "message": "bad cell"}}
            result = tools_slides.gdocs_slides_fill_table("pid", "tbl", [{"row": 0, "column": 0, "text": "x"}])
        self.assertIn("error", json.loads(result))
        mock_audit.assert_not_called()


class TestInsertImage(_GatedWriteBase):
    """gdocs_slides_insert_image shapes a gated createImage batchUpdate."""

    def test_happy_path_minimal(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"replies": [{"createImage": {"objectId": "img1"}}]}
            result = tools_slides.gdocs_slides_insert_image("pid", "slide1", "https://img/x.png")

        self.assertNotIn("error", json.loads(result))
        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://slides.googleapis.com/v1/presentations/pid:batchUpdate")
        create = body["requests"][0]["createImage"]
        self.assertEqual(create["url"], "https://img/x.png")
        self.assertEqual(create["elementProperties"], {"pageObjectId": "slide1"})
        mock_audit.assert_called_once()

    def test_size_and_transform(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            tools_slides.gdocs_slides_insert_image(
                "pid", "slide1", "https://img/x.png",
                width_pt=200, height_pt=100, translate_x_pt=50, translate_y_pt=75,
            )
        props = mock_api.call_args[0][2]["requests"][0]["createImage"]["elementProperties"]
        self.assertEqual(props["size"]["width"], {"magnitude": 200, "unit": "PT"})
        self.assertEqual(props["size"]["height"], {"magnitude": 100, "unit": "PT"})
        self.assertEqual(props["transform"]["translateX"], 50)
        self.assertEqual(props["transform"]["translateY"], 75)
        self.assertEqual(props["transform"]["unit"], "PT")

    def test_size_requires_both_dimensions(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            tools_slides.gdocs_slides_insert_image("pid", "slide1", "https://img/x.png", width_pt=200)
        props = mock_api.call_args[0][2]["requests"][0]["createImage"]["elementProperties"]
        self.assertNotIn("size", props)

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            result = tools_slides.gdocs_slides_insert_image("pid", "slide1", "https://img/x.png")
        self.assertIn("Read-only", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_error_envelope_passed_through_no_audit(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 400, "message": "bad url"}}
            result = tools_slides.gdocs_slides_insert_image("pid", "slide1", "https://img/x.png")
        self.assertIn("error", json.loads(result))
        mock_audit.assert_not_called()

    def test_catches_exception(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("boom")
            result = tools_slides.gdocs_slides_insert_image("pid", "slide1", "https://img/x.png")
        self.assertIn("boom", json.loads(result)["error"])


class TestAllowListGate(_GatedWriteBase):
    """Fill writes honor the folder allow-list via policy.gate_write (parent lookup)."""

    def test_replace_blocked_when_parent_not_allowed(self):
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "allowed_folder"
        with patch("policy.doc_parent_folder", return_value="other_folder"), \
             patch("policy.api") as mock_api:
            result = tools_slides.gdocs_slides_replace_all_text("pid", {"a": "b"})
        self.assertIn("not in allowed folder", json.loads(result)["error"].lower())
        mock_api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
