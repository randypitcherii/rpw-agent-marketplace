#!/usr/bin/env python3
"""
Google Sheets (API v4) tools for the Google Docs MCP server.

Values read/write/append/clear plus a raw ``spreadsheets.batchUpdate`` formatting
passthrough. Registered on the shared ``app.mcp`` instance alongside the core
Docs tools (``mcp_server``) and the media/collab tools (``tools_media``), and
ride the SAME authenticated client + ``policy`` gating those use — Sheets v4
needs no new dependency and no separate credential store (#197).

Reads are ungated (like ``gdocs_read``). Writes go through ``policy.gate_write``
so read-only mode, the folder allow-list, and audit logging apply exactly as for
the Docs write tools. Every spreadsheet argument accepts a raw ID or a full
Sheets URL and is normalized via ``sheets_ops.normalize_spreadsheet_id``.

All ranges use A1 notation, e.g. ``Sheet1!A1:C10``, ``Sheet1!A:A`` (whole
column), ``'Q3 Data'!A1`` (quote sheet names with spaces). ``values`` is a list
of rows (each row a list of cells): ``[["Name", "Score"], ["Ann", 91]]``.
"""

import json
from typing import Any, List

import policy
import sheets_ops
from app import mcp
from sheets_ops import SHEETS_BASE


@mcp.tool
def gsheets_read_values(spreadsheet_id: str, range: str) -> str:
    """Read cell values from a Google Sheet range (Sheets API values.batchGet).

    spreadsheet_id: a raw spreadsheet ID or a full Sheets URL
      (https://docs.google.com/spreadsheets/d/<ID>/edit).
    range: A1 notation. Examples:
      - "Sheet1!A1:C10"  — a rectangular block
      - "Sheet1!A:A"     — an entire column
      - "Sheet1!2:2"     — an entire row
      - "'Q3 Data'!A1:B" — sheet name with a space (single-quote it)
      - "Sheet1"         — the sheet's whole used range
      Pass several ranges comma-separated ("Sheet1!A1:B2,Sheet2!A1:A5") to read
      them in one call.

    Returns the raw batchGet JSON: {"spreadsheetId", "valueRanges": [{"range",
    "majorDimension", "values": [[...], ...]}, ...]}. Cells are strings by
    default; empty trailing cells/rows are omitted by the API. On error the raw
    {"error": {...}} envelope is passed through (consistent with gdocs_read).
    """
    try:
        sid = sheets_ops.normalize_spreadsheet_id(spreadsheet_id)
        ranges = [r.strip() for r in range.split(",") if r.strip()]
        query = "&".join(f"ranges={sheets_ops.encode_range(r)}" for r in ranges)
        url = f"{SHEETS_BASE}/{sid}/values:batchGet"
        if query:
            url = f"{url}?{query}"
        return json.dumps(policy.api("GET", url), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gsheets_write_values(
    spreadsheet_id: str,
    range: str,
    values: List[List[Any]],
    value_input_option: str = "USER_ENTERED",
) -> str:
    """Overwrite a range with values (Sheets API values.update — gated write).

    spreadsheet_id: raw ID or full Sheets URL.
    range: A1 notation anchoring the top-left of the write, e.g. "Sheet1!A1".
      The written block extends right/down to fit ``values``; cells outside the
      block are left untouched. To blank cells first use gsheets_clear.
    values: list of rows, each a list of cells, e.g.
      [["Name", "Score"], ["Ann", 91], ["Bo", 88]]. Numbers/bools may be passed
      as JSON numbers/bools or strings.
    value_input_option: "USER_ENTERED" (default) parses inputs like the Sheets
      UI — "=SUM(A1:A2)" becomes a formula, "5" a number, "1/2" a date. Use
      "RAW" to store inputs verbatim as strings.

    Blocked in read-only mode and subject to the folder allow-list; appends an
    audit entry on success. Returns the raw values.update response
    ({"spreadsheetId", "updatedRange", "updatedRows", "updatedColumns",
    "updatedCells"}), or the {"error": ...} envelope on failure.
    """
    sid = sheets_ops.normalize_spreadsheet_id(spreadsheet_id)
    if value_input_option not in sheets_ops.VALID_VALUE_INPUT_OPTIONS:
        return json.dumps({
            "error": f"Invalid value_input_option '{value_input_option}'. "
                     f"Expected one of {sorted(sheets_ops.VALID_VALUE_INPUT_OPTIONS)}.",
        })
    err = policy.gate_write("gsheets_write_values", sid)
    if err:
        return json.dumps({"error": err})
    try:
        url = (
            f"{SHEETS_BASE}/{sid}/values/{sheets_ops.encode_range(range)}"
            f"?valueInputOption={value_input_option}"
        )
        resp = policy.api("PUT", url, {"range": range, "values": values})
        if "error" in resp:
            return json.dumps(resp)
        policy.append_audit("gsheets_write_values", sid, f"range={range}")
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gsheets_append_rows(
    spreadsheet_id: str,
    range: str,
    values: List[List[Any]],
    value_input_option: str = "USER_ENTERED",
) -> str:
    """Append rows after a table's last row (Sheets API values.append — gated write).

    Unlike gsheets_write_values (which overwrites at a fixed anchor), append
    finds the last row of the table that overlaps ``range`` and writes the new
    rows immediately below it — the natural "add records to a log/table" op.

    spreadsheet_id: raw ID or full Sheets URL.
    range: A1 notation identifying the table to append to, typically the whole
      sheet or its header, e.g. "Sheet1" or "Sheet1!A1".
    values: list of rows to append, e.g. [["Ann", 91], ["Bo", 88]].
    value_input_option: "USER_ENTERED" (default) or "RAW" — see gsheets_write_values.

    Uses insertDataOption=INSERT_ROWS so existing rows below the table shift down
    rather than being overwritten. Blocked in read-only mode, subject to the
    allow-list, audited on success. Returns the raw values.append response
    (includes "updates" with the affected range/cell counts), or {"error": ...}.
    """
    sid = sheets_ops.normalize_spreadsheet_id(spreadsheet_id)
    if value_input_option not in sheets_ops.VALID_VALUE_INPUT_OPTIONS:
        return json.dumps({
            "error": f"Invalid value_input_option '{value_input_option}'. "
                     f"Expected one of {sorted(sheets_ops.VALID_VALUE_INPUT_OPTIONS)}.",
        })
    err = policy.gate_write("gsheets_append_rows", sid)
    if err:
        return json.dumps({"error": err})
    try:
        url = (
            f"{SHEETS_BASE}/{sid}/values/{sheets_ops.encode_range(range)}:append"
            f"?valueInputOption={value_input_option}&insertDataOption=INSERT_ROWS"
        )
        resp = policy.api("POST", url, {"range": range, "values": values})
        if "error" in resp:
            return json.dumps(resp)
        policy.append_audit("gsheets_append_rows", sid, f"range={range}")
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gsheets_clear(spreadsheet_id: str, range: str) -> str:
    """Clear the values in a range, keeping formatting (values.clear — gated write).

    spreadsheet_id: raw ID or full Sheets URL.
    range: A1 notation to clear, e.g. "Sheet1!A2:C" (all rows below a header) or
      "Sheet1" (the whole sheet's values). Only cell *values* are removed —
      formatting, notes, and data validation are left intact. Use gsheets_format
      to change formatting.

    Blocked in read-only mode, subject to the allow-list, audited on success.
    Returns {"spreadsheetId", "clearedRange"} from the API, or {"error": ...}.
    """
    sid = sheets_ops.normalize_spreadsheet_id(spreadsheet_id)
    err = policy.gate_write("gsheets_clear", sid)
    if err:
        return json.dumps({"error": err})
    try:
        url = f"{SHEETS_BASE}/{sid}/values/{sheets_ops.encode_range(range)}:clear"
        resp = policy.api("POST", url, {})
        if "error" in resp:
            return json.dumps(resp)
        policy.append_audit("gsheets_clear", sid, f"range={range}")
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gsheets_format(spreadsheet_id: str, requests: List[dict]) -> str:
    """Apply raw spreadsheets.batchUpdate requests — formatting, structure, etc. (gated write).

    A passthrough to the Sheets ``spreadsheets.batchUpdate`` endpoint: ``requests``
    is the list of Request objects sent verbatim as {"requests": requests}. This
    is the escape hatch for everything beyond cell values — formatting, adding/
    deleting sheets, merges, frozen rows, conditional formats, column widths.

    Requests target sheets by numeric ``sheetId`` (the gid, 0 for the first
    sheet), NOT by name, and use 0-based half-open GridRange
    (startRowIndex inclusive, endRowIndex exclusive). Common shapes:

    Bold the header row:
      [{"repeatCell": {
          "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1},
          "cell": {"userEnteredFormat": {"textFormat": {"bold": true}}},
          "fields": "userEnteredFormat.textFormat.bold"}}]

    Set a solid background on A1:C1:
      [{"repeatCell": {
          "range": {"sheetId": 0, "startRowIndex": 0, "endRowIndex": 1,
                    "startColumnIndex": 0, "endColumnIndex": 3},
          "cell": {"userEnteredFormat": {"backgroundColor":
                    {"red": 0.85, "green": 0.85, "blue": 0.85}}},
          "fields": "userEnteredFormat.backgroundColor"}}]

    Freeze the top row:
      [{"updateSheetProperties": {
          "properties": {"sheetId": 0,
                         "gridProperties": {"frozenRowCount": 1}},
          "fields": "gridProperties.frozenRowCount"}}]

    Auto-resize columns A–C:
      [{"autoResizeDimensions": {"dimensions": {"sheetId": 0,
          "dimension": "COLUMNS", "startIndex": 0, "endIndex": 3}}}]

    spreadsheet_id: raw ID or full Sheets URL. Blocked in read-only mode,
    subject to the allow-list, audited on success. Returns the raw batchUpdate
    response (its "replies" list mirrors the requests), or {"error": ...}.
    """
    sid = sheets_ops.normalize_spreadsheet_id(spreadsheet_id)
    err = policy.gate_write("gsheets_format", sid)
    if err:
        return json.dumps({"error": err})
    try:
        url = f"{SHEETS_BASE}/{sid}:batchUpdate"
        resp = policy.api("POST", url, {"requests": requests})
        if "error" in resp:
            return json.dumps(resp)
        policy.append_audit("gsheets_format", sid, f"requests={len(requests)}")
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})
