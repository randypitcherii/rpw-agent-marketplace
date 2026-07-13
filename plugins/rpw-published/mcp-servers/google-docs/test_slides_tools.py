#!/usr/bin/env python3
"""
Unit tests for the Slides MCP tools registered in ``tools_media.py``.

Covers the read/metadata tools (``gdocs_slides_read``, ``gdocs_slides_metadata``)
and the bonus write tool (``gdocs_slides_replace_text``). Fully mocked — no live
Google API calls. Read tools patch ``slides_read.read_presentation``; the write
tool patches the single ``policy.api`` entry point and honors the write gate.

Tools registered via ``@mcp.tool`` remain callable as plain module functions on
``tools_media`` (mirroring how ``mcp_server`` tests invoke ``gdocs_share``).
"""

import json
import os
import unittest
from unittest.mock import patch

import tools_media


class TestSlidesRead(unittest.TestCase):
    """gdocs_slides_read returns per-slide text JSON from read_presentation."""

    def test_returns_read_presentation_shape(self):
        payload = {
            "presentationId": "pid",
            "title": "Deck",
            "url": "https://docs.google.com/presentation/d/pid/edit",
            "slideCount": 1,
            "slides": [
                {
                    "objectId": "slide_1",
                    "index": 0,
                    "text": "Title\nBody",
                    "notes": "Speaker note",
                    "pageElementIds": ["el_1"],
                }
            ],
        }
        with patch("slides_read.read_presentation") as mock_read:
            mock_read.return_value = payload
            result = tools_media.gdocs_slides_read("pid")

        data = json.loads(result)
        self.assertEqual(data["presentationId"], "pid")
        self.assertEqual(data["slideCount"], 1)
        self.assertEqual(data["slides"][0]["notes"], "Speaker note")
        mock_read.assert_called_once_with("pid")

    def test_accepts_url(self):
        url = "https://docs.google.com/presentation/d/pid/edit"
        with patch("slides_read.read_presentation") as mock_read:
            mock_read.return_value = {"presentationId": "pid", "slides": [], "slideCount": 0}
            tools_media.gdocs_slides_read(url)
        mock_read.assert_called_once_with(url)

    def test_catches_exception(self):
        with patch("slides_read.read_presentation") as mock_read:
            mock_read.side_effect = RuntimeError("boom")
            result = tools_media.gdocs_slides_read("pid")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("boom", data["error"])


class TestSlidesMetadata(unittest.TestCase):
    """gdocs_slides_metadata returns slide count + object IDs."""

    def test_returns_count_and_object_ids(self):
        payload = {
            "presentationId": "pid",
            "title": "Deck",
            "url": "https://docs.google.com/presentation/d/pid/edit",
            "slideCount": 2,
            "slides": [
                {"objectId": "slide_1", "index": 0, "text": "", "notes": "", "pageElementIds": []},
                {"objectId": "slide_2", "index": 1, "text": "", "notes": "", "pageElementIds": []},
            ],
        }
        with patch("slides_read.read_presentation") as mock_read:
            mock_read.return_value = payload
            result = tools_media.gdocs_slides_metadata("pid")

        data = json.loads(result)
        self.assertEqual(data["slideCount"], 2)
        self.assertEqual(data["slideObjectIds"], ["slide_1", "slide_2"])
        self.assertEqual(data["presentationId"], "pid")

    def test_passes_error_envelope_through(self):
        with patch("slides_read.read_presentation") as mock_read:
            mock_read.return_value = {"error": {"code": 404, "message": "nope"}}
            result = tools_media.gdocs_slides_metadata("pid")
        data = json.loads(result)
        self.assertIn("error", data)

    def test_catches_exception(self):
        with patch("slides_read.read_presentation") as mock_read:
            mock_read.side_effect = RuntimeError("kaboom")
            result = tools_media.gdocs_slides_metadata("pid")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("kaboom", data["error"])


class TestSlidesReplaceText(unittest.TestCase):
    """gdocs_slides_replace_text is a gated replaceAllText write."""

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = tools_media.gdocs_slides_replace_text("pid", "foo", "bar")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("Read-only", data["error"])

    def test_happy_path_batch_update_body(self):
        with patch("policy.api") as mock_api, \
             patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"replies": [{"replaceAllText": {"occurrencesChanged": 3}}]}
            result = tools_media.gdocs_slides_replace_text("pid", "foo", "bar", match_case=True)

        data = json.loads(result)
        self.assertNotIn("error", data)

        call = mock_api.call_args
        self.assertEqual(call[0][0], "POST")
        self.assertEqual(
            call[0][1],
            "https://slides.googleapis.com/v1/presentations/pid:batchUpdate",
        )
        req = call[0][2]["requests"][0]["replaceAllText"]
        self.assertEqual(req["replaceText"], "bar")
        self.assertEqual(req["containsText"]["text"], "foo")
        self.assertTrue(req["containsText"]["matchCase"])
        mock_audit.assert_called_once()

    def test_normalizes_url(self):
        url = "https://docs.google.com/presentation/d/pid/edit"
        with patch("policy.api") as mock_api, \
             patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            tools_media.gdocs_slides_replace_text(url, "foo", "bar")
        called_url = mock_api.call_args[0][1]
        self.assertEqual(
            called_url,
            "https://slides.googleapis.com/v1/presentations/pid:batchUpdate",
        )

    def test_error_envelope_passed_through(self):
        with patch("policy.api") as mock_api, \
             patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 403, "message": "denied"}}
            result = tools_media.gdocs_slides_replace_text("pid", "foo", "bar")
        data = json.loads(result)
        self.assertIn("error", data)
        mock_audit.assert_not_called()

    def test_catches_exception(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("net down")
            result = tools_media.gdocs_slides_replace_text("pid", "foo", "bar")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("net down", data["error"])


if __name__ == "__main__":
    unittest.main()
