"""
Google Sheets (API v4) helpers for the Google Docs MCP server.

Pure library module — it registers no MCP tools. It provides the ID/URL
normalizer and A1-range encoding used by the ``gsheets_*`` tools in
``tools_sheets.py``, mirroring how ``slides_read.normalize_presentation_id``
serves the ``gdocs_slides_*`` tools. Keeping these here lets tests exercise the
shaping logic without a live Google call.

The tools ride the SAME authenticated ``policy.api`` / ``auth`` client the Docs
and Slides tools use — Sheets v4 needs no new dependency and no separate
credential store. It does require the Google Sheets scope on the user's ADC
grant; the ``drive`` scope already present for the Docs tools covers it, but a
narrowly-scoped grant may need a re-auth that adds
``https://www.googleapis.com/auth/spreadsheets`` (see README setup + #74).
"""

import re
from urllib.parse import quote

# Base URL for the Sheets API v4 spreadsheets resource.
SHEETS_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# Matches the ID segment of a Google Sheets URL, e.g.
#   https://docs.google.com/spreadsheets/d/<ID>/edit#gid=0
#   https://docs.google.com/spreadsheets/d/<ID>
_SPREADSHEET_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")

# valueInputOption values accepted by values.update / values.append.
VALID_VALUE_INPUT_OPTIONS = frozenset({"USER_ENTERED", "RAW"})


def normalize_spreadsheet_id(spreadsheet_id_or_url: str) -> str:
    """Return the bare spreadsheet ID from a raw ID or a full Sheets URL.

    Accepts either a raw spreadsheet ID (returned unchanged) or a full Google
    Sheets URL such as ``https://docs.google.com/spreadsheets/d/<ID>/edit#gid=0``
    and extracts the ``<ID>`` segment. Surrounding whitespace is stripped.
    """
    if not spreadsheet_id_or_url:
        return ""
    value = spreadsheet_id_or_url.strip()
    match = _SPREADSHEET_URL_RE.search(value)
    if match:
        return match.group(1)
    return value


def encode_range(a1_range: str) -> str:
    """Percent-encode an A1-notation range for use in a Sheets API URL path.

    A1 ranges embed ``!`` (sheet separator), ``:`` (cell-range separator), and
    sheet names may contain spaces or other reserved characters, none of which
    are URL-path-safe. ``safe=""`` encodes every reserved character so e.g.
    ``'Sheet 1'!A1:B2`` round-trips correctly.
    """
    return quote(a1_range, safe="")
