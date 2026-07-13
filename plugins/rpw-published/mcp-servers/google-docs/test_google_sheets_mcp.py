#!/usr/bin/env python3
"""
Unit tests for the Google Sheets (API v4) MCP tools in ``tools_sheets.py`` and
the ``sheets_ops`` helper library.

Fully mocked — no live Google API calls. The tools call the single
``policy.api`` entry point, so each test patches ``policy.api`` and asserts the
HTTP method, URL (endpoint + query params), and request body the tool shaped —
the same pattern the Slides suite (``test_slides_tools.py``) uses. Gating tests
drive the read-only / allow-list paths through ``policy``.

Tools registered via ``@mcp.tool`` remain callable as plain module functions on
``tools_sheets`` (mirroring how the Slides tests invoke ``gdocs_slides_*``).
"""

import json
import os
import unittest
from unittest.mock import patch

import sheets_ops
import tools_sheets


class TestNormalizeSpreadsheetId(unittest.TestCase):
    """sheets_ops.normalize_spreadsheet_id accepts a raw ID or a full URL."""

    def test_raw_id_unchanged(self):
        self.assertEqual(sheets_ops.normalize_spreadsheet_id("abc123_-XYZ"), "abc123_-XYZ")

    def test_extracts_id_from_url(self):
        url = "https://docs.google.com/spreadsheets/d/1AbC-dEf_123/edit#gid=0"
        self.assertEqual(sheets_ops.normalize_spreadsheet_id(url), "1AbC-dEf_123")

    def test_extracts_id_from_url_no_suffix(self):
        url = "https://docs.google.com/spreadsheets/d/1AbC-dEf_123"
        self.assertEqual(sheets_ops.normalize_spreadsheet_id(url), "1AbC-dEf_123")

    def test_strips_whitespace(self):
        self.assertEqual(sheets_ops.normalize_spreadsheet_id("  sid  "), "sid")

    def test_empty(self):
        self.assertEqual(sheets_ops.normalize_spreadsheet_id(""), "")


class TestEncodeRange(unittest.TestCase):
    """sheets_ops.encode_range percent-encodes reserved A1 characters."""

    def test_encodes_bang_and_colon(self):
        self.assertEqual(sheets_ops.encode_range("Sheet1!A1:B2"), "Sheet1%21A1%3AB2")

    def test_encodes_spaces_in_sheet_name(self):
        # 'Q3 Data'!A1 — quote and space both encoded
        self.assertEqual(sheets_ops.encode_range("'Q3 Data'!A1"), "%27Q3%20Data%27%21A1")


class TestReadValues(unittest.TestCase):
    """gsheets_read_values shapes a values:batchGet GET (ungated)."""

    def test_single_range_batchget(self):
        with patch("policy.api") as mock_api:
            mock_api.return_value = {
                "spreadsheetId": "sid",
                "valueRanges": [{"range": "Sheet1!A1:B2", "values": [["a", "b"]]}],
            }
            result = tools_sheets.gsheets_read_values("sid", "Sheet1!A1:B2")

        data = json.loads(result)
        self.assertEqual(data["valueRanges"][0]["values"], [["a", "b"]])
        method, url = mock_api.call_args[0][0], mock_api.call_args[0][1]
        self.assertEqual(method, "GET")
        self.assertEqual(
            url,
            "https://sheets.googleapis.com/v4/spreadsheets/sid/values:batchGet"
            "?ranges=Sheet1%21A1%3AB2",
        )

    def test_multiple_comma_separated_ranges(self):
        with patch("policy.api") as mock_api:
            mock_api.return_value = {"spreadsheetId": "sid", "valueRanges": []}
            tools_sheets.gsheets_read_values("sid", "Sheet1!A1:B2, Sheet2!A1:A5")
        url = mock_api.call_args[0][1]
        self.assertEqual(
            url,
            "https://sheets.googleapis.com/v4/spreadsheets/sid/values:batchGet"
            "?ranges=Sheet1%21A1%3AB2&ranges=Sheet2%21A1%3AA5",
        )

    def test_normalizes_url(self):
        with patch("policy.api") as mock_api:
            mock_api.return_value = {"valueRanges": []}
            tools_sheets.gsheets_read_values(
                "https://docs.google.com/spreadsheets/d/SID99/edit#gid=0", "Sheet1!A1"
            )
        url = mock_api.call_args[0][1]
        self.assertTrue(url.startswith("https://sheets.googleapis.com/v4/spreadsheets/SID99/"))

    def test_error_envelope_passed_through(self):
        with patch("policy.api") as mock_api:
            mock_api.return_value = {"error": {"code": 404, "message": "nope"}}
            result = tools_sheets.gsheets_read_values("sid", "Sheet1!A1")
        self.assertIn("error", json.loads(result))

    def test_catches_exception(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("net down")
            result = tools_sheets.gsheets_read_values("sid", "Sheet1!A1")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("net down", data["error"])


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


class TestWriteValues(_GatedWriteBase):
    """gsheets_write_values shapes a gated values.update PUT."""

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            result = tools_sheets.gsheets_write_values("sid", "Sheet1!A1", [["x"]])
        data = json.loads(result)
        self.assertIn("Read-only", data["error"])
        mock_api.assert_not_called()

    def test_happy_path_put_body_and_query(self):
        rows = [["Name", "Score"], ["Ann", 91]]
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"updatedCells": 4}
            result = tools_sheets.gsheets_write_values("sid", "Sheet1!A1", rows)

        self.assertNotIn("error", json.loads(result))
        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "PUT")
        self.assertEqual(
            url,
            "https://sheets.googleapis.com/v4/spreadsheets/sid/values/Sheet1%21A1"
            "?valueInputOption=USER_ENTERED",
        )
        self.assertEqual(body, {"range": "Sheet1!A1", "values": rows})
        mock_audit.assert_called_once()

    def test_raw_value_input_option(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit"):
            mock_api.return_value = {"updatedCells": 1}
            tools_sheets.gsheets_write_values("sid", "Sheet1!A1", [["=1+1"]], value_input_option="RAW")
        url = mock_api.call_args[0][1]
        self.assertTrue(url.endswith("?valueInputOption=RAW"))

    def test_invalid_value_input_option_rejected(self):
        with patch("policy.api") as mock_api:
            result = tools_sheets.gsheets_write_values("sid", "Sheet1!A1", [["x"]], value_input_option="BOGUS")
        data = json.loads(result)
        self.assertIn("Invalid value_input_option", data["error"])
        mock_api.assert_not_called()

    def test_error_envelope_passed_through_no_audit(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 403, "message": "denied"}}
            result = tools_sheets.gsheets_write_values("sid", "Sheet1!A1", [["x"]])
        self.assertIn("error", json.loads(result))
        mock_audit.assert_not_called()

    def test_catches_exception(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("boom")
            result = tools_sheets.gsheets_write_values("sid", "Sheet1!A1", [["x"]])
        self.assertIn("boom", json.loads(result)["error"])


class TestAppendRows(_GatedWriteBase):
    """gsheets_append_rows shapes a gated values:append POST with INSERT_ROWS."""

    def test_happy_path_append_body_and_query(self):
        rows = [["Ann", 91], ["Bo", 88]]
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"updates": {"updatedRows": 2}}
            result = tools_sheets.gsheets_append_rows("sid", "Sheet1", rows)

        self.assertNotIn("error", json.loads(result))
        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            url,
            "https://sheets.googleapis.com/v4/spreadsheets/sid/values/Sheet1:append"
            "?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS",
        )
        self.assertEqual(body, {"range": "Sheet1", "values": rows})
        mock_audit.assert_called_once()

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            result = tools_sheets.gsheets_append_rows("sid", "Sheet1", [["x"]])
        self.assertIn("Read-only", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_invalid_value_input_option_rejected(self):
        with patch("policy.api") as mock_api:
            result = tools_sheets.gsheets_append_rows("sid", "Sheet1", [["x"]], value_input_option="BOGUS")
        self.assertIn("Invalid value_input_option", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_catches_exception(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("boom")
            result = tools_sheets.gsheets_append_rows("sid", "Sheet1", [["x"]])
        self.assertIn("boom", json.loads(result)["error"])


class TestClear(_GatedWriteBase):
    """gsheets_clear shapes a gated values:clear POST with an empty body."""

    def test_happy_path(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"spreadsheetId": "sid", "clearedRange": "Sheet1!A2:C9"}
            result = tools_sheets.gsheets_clear("sid", "Sheet1!A2:C")

        self.assertNotIn("error", json.loads(result))
        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(
            url,
            "https://sheets.googleapis.com/v4/spreadsheets/sid/values/Sheet1%21A2%3AC:clear",
        )
        self.assertEqual(body, {})
        mock_audit.assert_called_once()

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            result = tools_sheets.gsheets_clear("sid", "Sheet1!A1:C9")
        self.assertIn("Read-only", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_error_envelope_passed_through_no_audit(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 400, "message": "bad range"}}
            result = tools_sheets.gsheets_clear("sid", "Sheet1!A1")
        self.assertIn("error", json.loads(result))
        mock_audit.assert_not_called()


class TestFormat(_GatedWriteBase):
    """gsheets_format shapes a gated spreadsheets:batchUpdate POST (raw passthrough)."""

    def test_happy_path_passes_requests_verbatim(self):
        requests = [
            {
                "repeatCell": {
                    "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
                    "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                    "fields": "userEnteredFormat.textFormat.bold",
                }
            }
        ]
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"spreadsheetId": "sid", "replies": [{}]}
            result = tools_sheets.gsheets_format("sid", requests)

        self.assertNotIn("error", json.loads(result))
        method, url, body = mock_api.call_args[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://sheets.googleapis.com/v4/spreadsheets/sid:batchUpdate")
        self.assertEqual(body, {"requests": requests})
        mock_audit.assert_called_once()

    def test_read_only_blocks(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        with patch("policy.api") as mock_api:
            result = tools_sheets.gsheets_format("sid", [{}])
        self.assertIn("Read-only", json.loads(result)["error"])
        mock_api.assert_not_called()

    def test_error_envelope_passed_through_no_audit(self):
        with patch("policy.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.return_value = {"error": {"code": 400, "message": "bad request"}}
            result = tools_sheets.gsheets_format("sid", [{"bogus": {}}])
        self.assertIn("error", json.loads(result))
        mock_audit.assert_not_called()

    def test_catches_exception(self):
        with patch("policy.api") as mock_api:
            mock_api.side_effect = RuntimeError("boom")
            result = tools_sheets.gsheets_format("sid", [{}])
        self.assertIn("boom", json.loads(result)["error"])


class TestAllowListGate(_GatedWriteBase):
    """Writes honor the folder allow-list via policy.gate_write (parent lookup)."""

    def test_write_blocked_when_parent_not_allowed(self):
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "allowed_folder"
        with patch("policy.doc_parent_folder", return_value="other_folder"), \
             patch("policy.api") as mock_api:
            result = tools_sheets.gsheets_write_values("sid", "Sheet1!A1", [["x"]])
        self.assertIn("not in allowed folder", json.loads(result)["error"].lower())
        mock_api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
