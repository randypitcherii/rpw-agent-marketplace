#!/usr/bin/env python3
"""
Google Slides template-fill tools for the Google Docs MCP server (#196).

The write half of the "data → customer-ready deck" motion: copy a template deck
(never mutate the master), map ``{{placeholders}}`` to values in one batchUpdate,
fill table cells, and drop an image onto a slide. These complement the Slides
read/create/single-replace tools already living in ``tools_media`` — this module
adds the batch-fill surface an agent needs to *populate* a copied template.

Everything rides the SAME authenticated ``policy.api`` / ``auth`` client the Docs
and Sheets tools use (Slides v1 + Drive v3 — zero new dependency, no separate
credential store). Writes go through ``policy.gate_write`` so read-only mode, the
folder allow-list, and audit logging apply exactly as for the Docs write tools.
Every presentation argument accepts a raw ID or a full Slides URL and is
normalized via ``slides_read.normalize_presentation_id``.

Google's explicit merge-template guidance is to copy the template and edit the
copy — ``gdocs_slides_copy_template`` does the Drive ``files.copy`` so the master
is never touched.
"""

import json
from typing import Any, List, Optional

import policy
import slides_read
from app import mcp

# API bases. Slides batchUpdate applies structural/text edits; Drive files.copy
# clones a template deck without touching the original.
SLIDES_BASE = "https://slides.googleapis.com/v1/presentations"
DRIVE_FILES_BASE = "https://www.googleapis.com/drive/v3/files"


def _batch_update(pres_id: str, requests: List[dict]) -> dict:
    """POST a Slides presentations:batchUpdate with the given request list."""
    return policy.api(
        "POST",
        f"{SLIDES_BASE}/{pres_id}:batchUpdate",
        {"requests": requests},
    )


@mcp.tool
def gdocs_slides_copy_template(template_id: str, title: str, folder_id: str = "") -> str:
    """Copy a Slides template deck to a new presentation (Drive files.copy — gated write).

    The template-fill entry point. Google's guidance is to NEVER edit a shared
    master template — copy it, then populate the copy with the other Slides tools.
    This clones ``template_id`` into a brand-new deck titled ``title`` and returns
    its id, so the rest of the fill runs against the copy.

    template_id: the master deck — a raw presentation ID or a full Slides URL.
    title: the new deck's name (e.g. "Acme — Quarterly Technical Plan").
    folder_id: optional Drive folder to place the copy in; omit for the caller's
      root. Subject to the folder allow-list when set.

    Blocked in read-only mode, audited on success. Returns JSON
    {"status": "copied", "presentationId", "url"} for the NEW deck, or the raw
    {"error": ...} envelope on failure.

    Typical flow:
      1. gdocs_slides_copy_template(master_id, "Acme QBR") -> new_id
      2. gdocs_slides_replace_all_text(new_id, {"{{account}}": "Acme", ...})
      3. gdocs_slides_fill_table(new_id, table_id, [...])
      4. gdocs_slides_insert_image(new_id, slide_id, image_url)
    """
    tid = slides_read.normalize_presentation_id(template_id)
    err = policy.gate_write("slides_copy_template", "new")
    if err:
        return json.dumps({"error": err})
    if folder_id and not policy.is_folder_allowed(folder_id):
        return json.dumps({"error": f"Target folder {folder_id} not in allow-list"})
    try:
        body: dict[str, Any] = {"name": title}
        if folder_id:
            body["parents"] = [folder_id]
        resp = policy.api(
            "POST",
            f"{DRIVE_FILES_BASE}/{tid}/copy?fields=id,name,parents",
            body,
        )
        if "error" in resp or "id" not in resp:
            return json.dumps(resp if "error" in resp else {"error": str(resp)})
        new_id = resp["id"]
        policy.append_audit("slides_copy_template", new_id, f"from={tid}")
        return json.dumps({
            "status": "copied",
            "presentationId": new_id,
            "url": f"https://docs.google.com/presentation/d/{new_id}/edit",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "hint": "Slides/Drive API may need to be enabled"})


@mcp.tool
def gdocs_slides_replace_all_text(
    presentation_id: str,
    replacements: dict,
    match_case: bool = False,
) -> str:
    """Fill many ``{{placeholders}}`` in one batchUpdate (Slides replaceAllText — gated write).

    The bulk template-merge primitive: pass a mapping of find-text → replace-text
    and every occurrence of each key across the whole deck (all slides, shapes,
    and table cells) is replaced in a single atomic batchUpdate. Prefer this over
    calling the single-pair ``gdocs_slides_replace_text`` N times.

    presentation_id: a raw presentation ID or a full Slides URL.
    replacements: a dict of literal find-strings to their replacements, e.g.
      {
        "{{account}}": "Acme",
        "{{quarter}}": "Q3 FY26",
        "{{owner_name}}": "Jordan",
      }
      Keys are matched verbatim — include the braces exactly as they appear in
      the template. Values are coerced to strings.
    match_case: whether matching is case-sensitive (default False).

    Blocked in read-only mode, subject to the allow-list, audited on success.
    Returns the raw Slides batchUpdate response (its "replies" list carries an
    ``occurrencesChanged`` per request — 0 means that placeholder wasn't found),
    or {"error": ...}.
    """
    pres_id = slides_read.normalize_presentation_id(presentation_id)
    if not replacements:
        return json.dumps({"error": "replacements mapping is empty"})
    err = policy.gate_write("slides_replace_all_text", pres_id)
    if err:
        return json.dumps({"error": err})
    try:
        requests = [
            {
                "replaceAllText": {
                    "replaceText": str(replace),
                    "containsText": {"text": find, "matchCase": match_case},
                }
            }
            for find, replace in replacements.items()
        ]
        resp = _batch_update(pres_id, requests)
        if "error" in resp:
            return json.dumps(resp)
        policy.append_audit("slides_replace_all_text", pres_id, f"keys={len(requests)}")
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_slides_fill_table(
    presentation_id: str,
    table_object_id: str,
    cells: List[dict],
    clear_existing: bool = False,
) -> str:
    """Write text into specific Slides table cells (Slides insertText — gated write).

    Populates individual cells of an existing table by (row, column). Use this to
    fill a data table in a copied template — get ``table_object_id`` from
    ``gdocs_slides_read`` (a slide's ``pageElementIds``) or ``gdocs_slides_metadata``.

    presentation_id: a raw presentation ID or a full Slides URL.
    table_object_id: the objectId of the target table page element.
    cells: a list of cell specs, each {"row": <int>, "column": <int>,
      "text": <str>}, 0-indexed, e.g.
        [
          {"row": 0, "column": 0, "text": "Metric"},
          {"row": 1, "column": 0, "text": "Spend"},
          {"row": 1, "column": 1, "text": "$1.2M"},
        ]
      Text is inserted at the start of each cell (insertionIndex 0).
    clear_existing: when True, delete the cell's current text before inserting —
      use for cells that already contain placeholder/prior text. Leave False
      (default) for empty cells; deleting an already-empty cell errors on the
      Slides API. For cells holding ``{{placeholder}}`` tokens, prefer
      ``gdocs_slides_replace_all_text`` instead.

    Blocked in read-only mode, subject to the allow-list, audited on success.
    Returns the raw Slides batchUpdate response, or {"error": ...}. An empty
    ``cells`` list is rejected before any API call.
    """
    pres_id = slides_read.normalize_presentation_id(presentation_id)
    if not cells:
        return json.dumps({"error": "cells list is empty"})
    err = policy.gate_write("slides_fill_table", pres_id)
    if err:
        return json.dumps({"error": err})
    try:
        requests: List[dict] = []
        for cell in cells:
            location = {
                "rowIndex": cell["row"],
                "columnIndex": cell["column"],
            }
            if clear_existing:
                requests.append({
                    "deleteText": {
                        "objectId": table_object_id,
                        "cellLocation": location,
                        "textRange": {"type": "ALL"},
                    }
                })
            requests.append({
                "insertText": {
                    "objectId": table_object_id,
                    "cellLocation": location,
                    "text": str(cell["text"]),
                    "insertionIndex": 0,
                }
            })
        resp = _batch_update(pres_id, requests)
        if "error" in resp:
            return json.dumps(resp)
        policy.append_audit("slides_fill_table", pres_id, f"cells={len(cells)}")
        return json.dumps(resp, ensure_ascii=False)
    except KeyError as e:
        return json.dumps({"error": f"cell missing required key: {e}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_slides_insert_image(
    presentation_id: str,
    page_object_id: str,
    image_url: str,
    width_pt: Optional[float] = None,
    height_pt: Optional[float] = None,
    translate_x_pt: Optional[float] = None,
    translate_y_pt: Optional[float] = None,
) -> str:
    """Insert an image from a URL onto a slide (Slides createImage — gated write).

    Places a public image URL as a new picture element on a given slide page. Get
    ``page_object_id`` (the slide's objectId) from ``gdocs_slides_metadata`` or
    ``gdocs_slides_read``.

    presentation_id: a raw presentation ID or a full Slides URL.
    page_object_id: the objectId of the slide page to place the image on.
    image_url: a publicly accessible image URL (e.g. from ``gdocs_upload_image``,
      which uploads a local file to Drive and grants public read).
    width_pt / height_pt: optional size in points. Pass BOTH to size the image;
      omit both for the API's default sizing.
    translate_x_pt / translate_y_pt: optional top-left offset in points from the
      slide origin. Omit to let the API position it (top-left corner).

    Blocked in read-only mode, subject to the allow-list, audited on success.
    Returns the raw Slides batchUpdate response (its reply carries the created
    image's ``objectId``), or {"error": ...}.

    To swap a placeholder shape for an image instead of adding a new one, note the
    Slides API also supports replaceAllShapesWithImage — not exposed here; use
    createImage-based insertion plus positioning for template fill.
    """
    pres_id = slides_read.normalize_presentation_id(presentation_id)
    err = policy.gate_write("slides_insert_image", pres_id)
    if err:
        return json.dumps({"error": err})
    try:
        element_properties: dict[str, Any] = {"pageObjectId": page_object_id}
        if width_pt is not None and height_pt is not None:
            element_properties["size"] = {
                "width": {"magnitude": width_pt, "unit": "PT"},
                "height": {"magnitude": height_pt, "unit": "PT"},
            }
        if translate_x_pt is not None or translate_y_pt is not None:
            element_properties["transform"] = {
                "scaleX": 1,
                "scaleY": 1,
                "translateX": translate_x_pt or 0,
                "translateY": translate_y_pt or 0,
                "unit": "PT",
            }
        req = {"createImage": {"url": image_url, "elementProperties": element_properties}}
        resp = _batch_update(pres_id, [req])
        if "error" in resp:
            return json.dumps(resp)
        policy.append_audit("slides_insert_image", pres_id, f"page={page_object_id}")
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})
