#!/usr/bin/env python3
"""
Unit tests for the Google Slides read/metadata/replace-text surface.

Mirrors the style of ``test_google_docs_mcp.py``: fully mocked (no live Google
API calls), patching the SINGLE library entry points that all network access
flows through. The read-path library (``slides_read``) is driven through
``auth.api`` — the one patch point — and the write-path MCP tool
(``gdocs_slides_replace_text``) is driven through ``policy.api`` plus the same
read-only/allow-list gate the docs tools use.

This file is a sibling to ``test_slides_read.py`` / ``test_slides_tools.py``
(which cover the same surface at finer grain). It exists so the Slides feature
is also exercised end-to-end through the docs-server-style harness with a single
fake ``presentations.get`` fixture containing shape text, a table, and speaker
notes, per the acceptance criteria: per-slide text extraction, metadata
(slide count + object IDs), ID-vs-URL normalization, error/404 handling, and the
replace-text ``batchUpdate`` gating (including read-only-mode rejection).
"""

import json
import os
import unittest
from unittest.mock import patch

import slides_read
import tools_media


# ---------------------------------------------------------------------------
# Fake presentations.get response builders
# ---------------------------------------------------------------------------

def _shape_element(object_id, content):
    """A page element wrapping a shape with a single textRun."""
    return {
        "objectId": object_id,
        "shape": {"text": {"textElements": [{"textRun": {"content": content}}]}},
    }


def _table_element(object_id, rows):
    """A page element wrapping a table. ``rows`` is a list of lists of cell text."""
    table_rows = []
    for row in rows:
        cells = []
        for cell_text in row:
            cells.append(
                {"text": {"textElements": [{"textRun": {"content": cell_text}}]}}
            )
        table_rows.append({"tableCells": cells})
    return {"objectId": object_id, "table": {"tableRows": table_rows}}


def _fake_presentation():
    """A presentations.get response with shape text, a table, and speaker notes.

    Slide 1: a title shape + a body shape + a 2x2 table, with speaker notes.
    Slide 2: a single shape, no notes.
    """
    return {
        "presentationId": "PRES_ID",
        "title": "Quarterly Deck",
        "slides": [
            {
                "objectId": "slide_1",
                "pageElements": [
                    _shape_element("title_1", "Q3 Results\n"),
                    _shape_element("body_1", "Revenue up 12%"),
                    _table_element(
                        "table_1",
                        [["Metric", "Value"], ["Revenue", "$1.2M"]],
                    ),
                ],
                "slideProperties": {
                    "notesPage": {
                        "pageElements": [
                            _shape_element("notes_1", "Emphasize the growth trend"),
                        ]
                    }
                },
            },
            {
                "objectId": "slide_2",
                "pageElements": [
                    _shape_element("title_2", "Next Steps"),
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# Read-path library: slides_read.read_presentation (patch auth.api)
# ---------------------------------------------------------------------------

class TestSlidesReadPresentationLibrary(unittest.TestCase):
    """slides_read.read_presentation walks shapes, tables, and speaker notes.

    The single network entry point is ``auth.api`` — patched here.
    """

    def test_per_slide_text_extraction(self):
        with patch("auth.api") as mock_api:
            mock_api.return_value = _fake_presentation()
            result = slides_read.read_presentation("PRES_ID")

        self.assertEqual(result["presentationId"], "PRES_ID")
        self.assertEqual(result["title"], "Quarterly Deck")
        self.assertEqual(result["slideCount"], 2)

        s1 = result["slides"][0]
        self.assertEqual(s1["objectId"], "slide_1")
        self.assertEqual(s1["index"], 0)
        # Shape text from both title + body shapes.
        self.assertIn("Q3 Results", s1["text"])
        self.assertIn("Revenue up 12%", s1["text"])
        # Table cell text is rendered inline in the slide's text.
        for cell in ("Metric", "Value", "Revenue", "$1.2M"):
            self.assertIn(cell, s1["text"])
        # Speaker notes are extracted separately from the slide body text.
        self.assertIn("Emphasize the growth trend", s1["notes"])
        self.assertNotIn("Emphasize the growth trend", s1["text"])

        s2 = result["slides"][1]
        self.assertEqual(s2["objectId"], "slide_2")
        self.assertEqual(s2["index"], 1)
        self.assertIn("Next Steps", s2["text"])
        self.assertEqual(s2["notes"], "")

    def test_page_element_ids_captured(self):
        with patch("auth.api") as mock_api:
            mock_api.return_value = _fake_presentation()
            result = slides_read.read_presentation("PRES_ID")

        self.assertEqual(
            result["slides"][0]["pageElementIds"],
            ["title_1", "body_1", "table_1"],
        )
        self.assertEqual(result["slides"][1]["pageElementIds"], ["title_2"])

    def test_url_normalized_to_bare_id_before_api_call(self):
        url = "https://docs.google.com/presentation/d/PRES_ID/edit#slide=id.p1"
        with patch("auth.api") as mock_api:
            mock_api.return_value = _fake_presentation()
            slides_read.read_presentation(url)

        called_url = mock_api.call_args[0][1]
        self.assertEqual(
            called_url,
            "https://slides.googleapis.com/v1/presentations/PRES_ID",
        )

    def test_raw_id_passed_through_unchanged(self):
        with patch("auth.api") as mock_api:
            mock_api.return_value = _fake_presentation()
            slides_read.read_presentation("PRES_ID")

        self.assertEqual(
            mock_api.call_args[0][1],
            "https://slides.googleapis.com/v1/presentations/PRES_ID",
        )

    def test_error_envelope_passthrough_on_404(self):
        err = {"error": {"code": 404, "message": "Requested entity was not found."}}
        with patch("auth.api") as mock_api:
            mock_api.return_value = err
            result = slides_read.read_presentation("missing")

        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], 404)


# ---------------------------------------------------------------------------
# gdocs_slides_read (patch auth.api so the whole path runs)
# ---------------------------------------------------------------------------

class TestGdocsSlidesReadTool(unittest.TestCase):
    """gdocs_slides_read returns the read_presentation JSON as a string."""

    def test_returns_per_slide_json(self):
        with patch("auth.api") as mock_api:
            mock_api.return_value = _fake_presentation()
            data = json.loads(tools_media.gdocs_slides_read("PRES_ID"))

        self.assertEqual(data["presentationId"], "PRES_ID")
        self.assertEqual(data["slideCount"], 2)
        self.assertEqual(data["slides"][0]["notes"], "Emphasize the growth trend")
        self.assertIn("Q3 Results", data["slides"][0]["text"])

    def test_accepts_full_url(self):
        url = "https://docs.google.com/presentation/d/PRES_ID/edit"
        with patch("auth.api") as mock_api:
            mock_api.return_value = _fake_presentation()
            data = json.loads(tools_media.gdocs_slides_read(url))

        self.assertEqual(data["presentationId"], "PRES_ID")

    def test_404_error_surfaces(self):
        with patch("auth.api") as mock_api:
            mock_api.return_value = {"error": {"code": 404, "message": "nope"}}
            data = json.loads(tools_media.gdocs_slides_read("missing"))

        self.assertIn("error", data)

    def test_exception_caught_as_error(self):
        with patch("auth.api") as mock_api:
            mock_api.side_effect = RuntimeError("network boom")
            data = json.loads(tools_media.gdocs_slides_read("PRES_ID"))

        self.assertIn("error", data)
        self.assertIn("network boom", data["error"])


# ---------------------------------------------------------------------------
# gdocs_slides_metadata (patch auth.api)
# ---------------------------------------------------------------------------

class TestGdocsSlidesMetadataTool(unittest.TestCase):
    """gdocs_slides_metadata returns slide count + ordered slide object IDs."""

    def test_slide_count_and_object_ids(self):
        with patch("auth.api") as mock_api:
            mock_api.return_value = _fake_presentation()
            data = json.loads(tools_media.gdocs_slides_metadata("PRES_ID"))

        self.assertEqual(data["presentationId"], "PRES_ID")
        self.assertEqual(data["title"], "Quarterly Deck")
        self.assertEqual(data["slideCount"], 2)
        self.assertEqual(data["slideObjectIds"], ["slide_1", "slide_2"])
        # Metadata is a lightweight projection — no per-slide text/notes.
        self.assertNotIn("slides", data)

    def test_url_normalized(self):
        url = "https://docs.google.com/presentation/d/PRES_ID/edit"
        with patch("auth.api") as mock_api:
            mock_api.return_value = _fake_presentation()
            data = json.loads(tools_media.gdocs_slides_metadata(url))

        self.assertEqual(data["slideObjectIds"], ["slide_1", "slide_2"])
        self.assertEqual(
            mock_api.call_args[0][1],
            "https://slides.googleapis.com/v1/presentations/PRES_ID",
        )

    def test_404_error_passed_through(self):
        with patch("auth.api") as mock_api:
            mock_api.return_value = {"error": {"code": 404, "message": "not found"}}
            data = json.loads(tools_media.gdocs_slides_metadata("missing"))

        self.assertIn("error", data)


# ---------------------------------------------------------------------------
# gdocs_slides_replace_text — gated batchUpdate write (patch policy.api)
# ---------------------------------------------------------------------------

class TestGdocsSlidesReplaceText(unittest.TestCase):
    """gdocs_slides_replace_text is a gated replaceAllText batchUpdate write.

    All network access flows through ``policy.api`` — the single patch point,
    which also re-exports ``auth.api`` so the whole gate + write path runs
    without live credentials.
    """

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def test_read_only_mode_rejects_write(self):
        """Read-only mode blocks the write before any API call."""
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            data = json.loads(
                tools_media.gdocs_slides_replace_text("PRES_ID", "foo", "bar")
            )
        self.assertIn("error", data)
        self.assertIn("Read-only", data["error"])
        mock_api.assert_not_called()

    def test_happy_path_batch_update_body(self):
        with patch("policy.api") as mock_api, \
             patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {
                "replies": [{"replaceAllText": {"occurrencesChanged": 3}}]
            }
            data = json.loads(
                tools_media.gdocs_slides_replace_text(
                    "PRES_ID", "OldCo", "NewCo", match_case=True
                )
            )

        self.assertNotIn("error", data)

        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            url,
            "https://slides.googleapis.com/v1/presentations/PRES_ID:batchUpdate",
        )
        req = body["requests"][0]["replaceAllText"]
        self.assertEqual(req["replaceText"], "NewCo")
        self.assertEqual(req["containsText"]["text"], "OldCo")
        self.assertTrue(req["containsText"]["matchCase"])
        # Successful write is audited exactly once.
        mock_audit.assert_called_once()

    def test_match_case_defaults_false(self):
        with patch("policy.api") as mock_api, \
             patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            tools_media.gdocs_slides_replace_text("PRES_ID", "foo", "bar")

        body = mock_api.call_args[0][2]
        self.assertFalse(body["requests"][0]["replaceAllText"]["containsText"]["matchCase"])

    def test_url_normalized_before_batch_update(self):
        url = "https://docs.google.com/presentation/d/PRES_ID/edit"
        with patch("policy.api") as mock_api, \
             patch("policy.append_audit"):
            mock_api.return_value = {"replies": [{}]}
            tools_media.gdocs_slides_replace_text(url, "foo", "bar")

        self.assertEqual(
            mock_api.call_args[0][1],
            "https://slides.googleapis.com/v1/presentations/PRES_ID:batchUpdate",
        )

    def test_api_error_envelope_passed_through_and_not_audited(self):
        with patch("policy.api") as mock_api, \
             patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 403, "message": "denied"}}
            data = json.loads(
                tools_media.gdocs_slides_replace_text("PRES_ID", "foo", "bar")
            )

        self.assertIn("error", data)
        mock_audit.assert_not_called()

    def test_exception_caught_as_error(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("net down")
            data = json.loads(
                tools_media.gdocs_slides_replace_text("PRES_ID", "foo", "bar")
            )

        self.assertIn("error", data)
        self.assertIn("net down", data["error"])


if __name__ == "__main__":
    unittest.main()
