#!/usr/bin/env python3
"""
Unit tests for the Google Slides read-path library module (slides_read.py).

Fully mocked — no live Google API calls. Patches the single ``auth.api`` entry
point (mirroring the docs_read pattern) to feed synthetic Slides API responses.
"""

import unittest
from unittest.mock import patch

import slides_read


class TestNormalizePresentationId(unittest.TestCase):
    """normalize_presentation_id accepts a raw ID or a full Slides URL."""

    def test_raw_id_passthrough(self):
        self.assertEqual(slides_read.normalize_presentation_id("abc123XYZ"), "abc123XYZ")

    def test_full_edit_url(self):
        url = "https://docs.google.com/presentation/d/1AbCdEf_gh-IJ/edit"
        self.assertEqual(slides_read.normalize_presentation_id(url), "1AbCdEf_gh-IJ")

    def test_url_without_edit_suffix(self):
        url = "https://docs.google.com/presentation/d/1AbCdEf_gh-IJ"
        self.assertEqual(slides_read.normalize_presentation_id(url), "1AbCdEf_gh-IJ")

    def test_url_with_query_and_slide_fragment(self):
        url = "https://docs.google.com/presentation/d/PRES_ID/edit#slide=id.p1"
        self.assertEqual(slides_read.normalize_presentation_id(url), "PRES_ID")

    def test_whitespace_stripped(self):
        self.assertEqual(slides_read.normalize_presentation_id("  pid  "), "pid")

    def test_empty_string(self):
        self.assertEqual(slides_read.normalize_presentation_id(""), "")


def _shape_element(object_id, content):
    """Build a page element containing a shape with a single textRun."""
    return {
        "objectId": object_id,
        "shape": {
            "text": {
                "textElements": [
                    {"textRun": {"content": content}},
                ]
            }
        },
    }


class TestReadPresentation(unittest.TestCase):
    """read_presentation walks shapes, tables, and speaker notes."""

    def test_extracts_per_slide_shape_text_and_metadata(self):
        resp = {
            "presentationId": "pid",
            "title": "My Deck",
            "slides": [
                {
                    "objectId": "slide_1",
                    "pageElements": [
                        _shape_element("el_1", "Title text\n"),
                        _shape_element("el_2", "Body text"),
                    ],
                },
                {
                    "objectId": "slide_2",
                    "pageElements": [
                        _shape_element("el_3", "Second slide"),
                    ],
                },
            ],
        }
        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = slides_read.read_presentation("pid")

        self.assertEqual(result["presentationId"], "pid")
        self.assertEqual(result["title"], "My Deck")
        self.assertEqual(result["url"], "https://docs.google.com/presentation/d/pid/edit")
        self.assertEqual(result["slideCount"], 2)
        self.assertEqual(len(result["slides"]), 2)

        s1 = result["slides"][0]
        self.assertEqual(s1["objectId"], "slide_1")
        self.assertEqual(s1["index"], 0)
        self.assertIn("Title text", s1["text"])
        self.assertIn("Body text", s1["text"])
        self.assertEqual(s1["pageElementIds"], ["el_1", "el_2"])

        s2 = result["slides"][1]
        self.assertEqual(s2["objectId"], "slide_2")
        self.assertIn("Second slide", s2["text"])

    def test_normalizes_url_before_calling_api(self):
        resp = {"presentationId": "PRES_ID", "title": "T", "slides": []}
        url = "https://docs.google.com/presentation/d/PRES_ID/edit"
        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = slides_read.read_presentation(url)

        called_url = mock_api.call_args[0][1]
        self.assertEqual(
            called_url,
            "https://slides.googleapis.com/v1/presentations/PRES_ID",
        )
        self.assertEqual(result["presentationId"], "PRES_ID")

    def test_extracts_table_text(self):
        table_element = {
            "objectId": "tbl_1",
            "table": {
                "tableRows": [
                    {
                        "tableCells": [
                            {"text": {"textElements": [{"textRun": {"content": "H1"}}]}},
                            {"text": {"textElements": [{"textRun": {"content": "H2"}}]}},
                        ]
                    },
                    {
                        "tableCells": [
                            {"text": {"textElements": [{"textRun": {"content": "r1c1"}}]}},
                            {"text": {"textElements": [{"textRun": {"content": "r1c2"}}]}},
                        ]
                    },
                ]
            },
        }
        resp = {
            "presentationId": "pid",
            "title": "Deck",
            "slides": [{"objectId": "slide_1", "pageElements": [table_element]}],
        }
        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = slides_read.read_presentation("pid")

        text = result["slides"][0]["text"]
        for expected in ("H1", "H2", "r1c1", "r1c2"):
            self.assertIn(expected, text)

    def test_extracts_speaker_notes(self):
        resp = {
            "presentationId": "pid",
            "title": "Deck",
            "slides": [
                {
                    "objectId": "slide_1",
                    "pageElements": [_shape_element("el_1", "Visible")],
                    "slideProperties": {
                        "notesPage": {
                            "pageElements": [
                                _shape_element("notes_shape", "Speaker note content"),
                            ]
                        }
                    },
                }
            ],
        }
        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = slides_read.read_presentation("pid")

        slide = result["slides"][0]
        self.assertIn("Speaker note content", slide["notes"])
        self.assertNotIn("Speaker note content", slide["text"])

    def test_error_envelope_passthrough(self):
        err = {"error": {"code": 404, "message": "Requested entity was not found."}}
        with patch("auth.api") as mock_api:
            mock_api.return_value = err
            result = slides_read.read_presentation("missing")

        self.assertIn("error", result)
        self.assertEqual(result["error"]["code"], 404)

    def test_empty_presentation_graceful(self):
        resp = {"presentationId": "pid", "title": "Empty", "slides": []}
        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = slides_read.read_presentation("pid")

        self.assertEqual(result["slideCount"], 0)
        self.assertEqual(result["slides"], [])

    def test_missing_slides_key_graceful(self):
        resp = {"presentationId": "pid", "title": "No slides key"}
        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = slides_read.read_presentation("pid")

        self.assertEqual(result["slideCount"], 0)
        self.assertEqual(result["slides"], [])


if __name__ == "__main__":
    unittest.main()
