"""
Read-path operations for Google Slides presentations.

``read_presentation`` extracts per-slide text from a presentation via the Slides
API ``presentations.get`` endpoint, walking shape text runs, table cells, and
speaker-notes shapes. A URL/ID normalizer (``normalize_presentation_id``) accepts
either a raw presentation ID or a full Google Slides URL and returns the bare ID.

This is a pure library module — it registers no MCP tools. All network calls go
through ``auth`` (module-qualified so tests patch a single point, ``auth.api``),
mirroring the pattern in ``docs_read.py``. Errors from the API surface as an
``{"error": ...}`` dict, consistent with ``read_doc``.

Reference pattern: the ``sanjay3290/ai-skills@google-slides`` skill's
``scripts/slides.py get-text``.
"""

import re
from typing import Any, Dict, List

import auth

# Matches the ID segment of a Google Slides URL, e.g.
#   https://docs.google.com/presentation/d/<ID>/edit
#   https://docs.google.com/presentation/d/<ID>
_PRESENTATION_URL_RE = re.compile(r"/presentation/d/([a-zA-Z0-9_-]+)")


def normalize_presentation_id(presentation_id_or_url: str) -> str:
    """Return the bare presentation ID from a raw ID or a full Slides URL.

    Accepts either a raw presentation ID (returned unchanged) or a full Google
    Slides URL such as ``https://docs.google.com/presentation/d/<ID>/edit`` and
    extracts the ``<ID>`` segment. Surrounding whitespace is stripped.
    """
    if not presentation_id_or_url:
        return ""
    value = presentation_id_or_url.strip()
    match = _PRESENTATION_URL_RE.search(value)
    if match:
        return match.group(1)
    return value


def _shape_text(shape: Dict[str, Any]) -> str:
    """Concatenate textRun content from a shape's text elements."""
    text = ""
    for element in shape.get("text", {}).get("textElements", []):
        text_run = element.get("textRun")
        if text_run:
            text += text_run.get("content", "")
    return text


def _table_text(table: Dict[str, Any]) -> str:
    """Render a Slides table as tab-separated rows for the plain-text read path."""
    rows: List[str] = []
    for row in table.get("tableRows", []):
        cells: List[str] = []
        for cell in row.get("tableCells", []):
            cells.append(_shape_text(cell).strip())
        rows.append("\t".join(cells).rstrip())
    return "\n".join(rows) + ("\n" if rows else "")


def _page_elements_text(page_elements: List[Dict[str, Any]]) -> str:
    """Extract text from a list of page elements (shapes + tables)."""
    text = ""
    for pe in page_elements:
        if "shape" in pe:
            text += _shape_text(pe["shape"])
        elif "table" in pe:
            text += _table_text(pe["table"])
    return text


def _notes_text(slide: Dict[str, Any]) -> str:
    """Extract speaker-notes text from a slide's notesPage shapes."""
    notes_page = slide.get("slideProperties", {}).get("notesPage", {})
    return _page_elements_text(notes_page.get("pageElements", []))


def read_presentation(presentation_id_or_url: str) -> Dict[str, Any]:
    """Read a presentation's per-slide text, tables, and speaker notes.

    Accepts a raw presentation ID or a full Google Slides URL. Returns a dict:

        {
            "presentationId": <id>,
            "title": <title>,
            "url": "https://docs.google.com/presentation/d/<id>/edit",
            "slideCount": <int>,
            "slides": [
                {
                    "objectId": <slide object id>,
                    "index": <int>,
                    "text": <concatenated shape + table text>,
                    "notes": <speaker-notes text>,
                    "pageElementIds": [<page element object ids>],
                },
                ...
            ],
        }

    On API error (e.g. 404), returns the raw ``{"error": ...}`` envelope,
    consistent with ``read_doc``. An empty/absent slides list yields an empty
    ``slides`` list and ``slideCount`` of 0.
    """
    presentation_id = normalize_presentation_id(presentation_id_or_url)
    resp = auth.api(
        "GET",
        f"https://slides.googleapis.com/v1/presentations/{presentation_id}",
    )
    if "error" in resp:
        return resp

    slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(resp.get("slides", [])):
        page_elements = slide.get("pageElements", [])
        slides.append({
            "objectId": slide.get("objectId", ""),
            "index": index,
            "text": _page_elements_text(page_elements),
            "notes": _notes_text(slide),
            "pageElementIds": [
                pe.get("objectId", "") for pe in page_elements
            ],
        })

    return {
        "presentationId": presentation_id,
        "title": resp.get("title", ""),
        "url": f"https://docs.google.com/presentation/d/{presentation_id}/edit",
        "slideCount": len(slides),
        "slides": slides,
    }
