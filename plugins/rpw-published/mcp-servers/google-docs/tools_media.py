#!/usr/bin/env python3
"""
Media and collaboration tools for the Google Docs MCP server.

Slides creation, sharing, in-doc search, person chips, and image
upload/insert. Registered on the shared ``app.mcp`` instance alongside the core
CRUD/tab tools in ``mcp_server``. Gating and Google API access go through
``policy`` (the single test patch point).
"""

import json
import os
from typing import Any, Optional

import policy
import slides_read
from app import mcp
from docs_read import read_doc


# --- Phase 4: slides, share, search, person-chip ---

@mcp.tool
def gdocs_slides_create(title: str, folder_id: str = "") -> str:
    """Create a Google Slides presentation. folder_id: optional; uses target folder if empty.
    Limitation: Requires Slides API; may fail if not enabled."""
    fid = folder_id or policy.target_folder()
    if not fid:
        return json.dumps({"error": "No folder_id and GDOCS_TARGET_FOLDER_ID not set"})
    try:
        resp = policy.api("POST", "https://slides.googleapis.com/v1/presentations", {"title": title})
        if "error" in resp:
            return json.dumps(resp)
        pres_id = resp.get("presentationId")
        # Move to folder via Drive API
        file_info = policy.api("GET", f"https://www.googleapis.com/drive/v3/files/{pres_id}?fields=parents")
        current = ",".join(file_info.get("parents", []))
        if current:
            policy.api(
                "PATCH",
                f"https://www.googleapis.com/drive/v3/files/{pres_id}?addParents={fid}&removeParents={current}",
            )
        return json.dumps({
            "status": "created",
            "presentationId": pres_id,
            "url": f"https://docs.google.com/presentation/d/{pres_id}/edit",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e), "hint": "Slides API may need to be enabled"})


@mcp.tool
def gdocs_slides_read(presentation_id: str) -> str:
    """Read a Google Slides presentation's per-slide text (incl. tables + speaker notes).

    presentation_id: a raw presentation ID or a full Google Slides URL.
    Returns JSON with presentationId, title, url, slideCount, and a slides list
    where each slide has objectId, index, text, notes, and pageElementIds.
    Limitation: Requires Slides API; may fail if not enabled."""
    try:
        out = slides_read.read_presentation(presentation_id)
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_slides_metadata(presentation_id: str) -> str:
    """Return a presentation's slide count and per-slide object IDs.

    presentation_id: a raw presentation ID or a full Google Slides URL.
    Returns JSON with presentationId, title, url, slideCount, and slideObjectIds
    (the ordered list of slide object IDs). On API error, the raw error envelope
    is passed through.
    Limitation: Requires Slides API; may fail if not enabled."""
    try:
        out = slides_read.read_presentation(presentation_id)
        if "error" in out:
            return json.dumps(out)
        return json.dumps({
            "presentationId": out.get("presentationId", ""),
            "title": out.get("title", ""),
            "url": out.get("url", ""),
            "slideCount": out.get("slideCount", 0),
            "slideObjectIds": [s.get("objectId", "") for s in out.get("slides", [])],
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_slides_replace_text(
    presentation_id: str,
    find: str,
    replace: str,
    match_case: bool = False,
) -> str:
    """Replace all occurrences of ``find`` with ``replace`` across a presentation.

    Basic replaceAllText write via the Slides presentations:batchUpdate endpoint.
    presentation_id: a raw presentation ID or a full Google Slides URL.
    match_case: whether the text match is case-sensitive (default False).
    Limitation: Requires Slides API; may fail if not enabled."""
    pres_id = slides_read.normalize_presentation_id(presentation_id)
    err = policy.gate_write("slides_replace_text", pres_id)
    if err:
        return json.dumps({"error": err})
    try:
        req = {
            "replaceAllText": {
                "replaceText": replace,
                "containsText": {"text": find, "matchCase": match_case},
            }
        }
        resp = policy.api(
            "POST",
            f"https://slides.googleapis.com/v1/presentations/{pres_id}:batchUpdate",
            {"requests": [req]},
        )
        if "error" in resp:
            return json.dumps(resp)
        policy.append_audit("slides_replace_text", pres_id, f"find={find[:50]}")
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_share(doc_id: str, email: str, role: str = "writer") -> str:
    """Share a doc with an email. role: reader, writer, or commenter."""
    if role not in ("reader", "writer", "commenter"):
        return json.dumps({"error": f"Invalid role: {role}"})
    err = policy.gate_write("share", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        # Create permission via Drive API
        body = {
            "type": "user",
            "role": role,
            "emailAddress": email,
        }
        resp = policy.api(
            "POST",
            f"https://www.googleapis.com/drive/v3/files/{doc_id}/permissions?sendNotificationEmail=false",
            body,
        )
        if "error" in resp:
            return json.dumps(resp)
        return json.dumps({"status": "shared", "documentId": doc_id, "email": email, "role": role})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_search(doc_id: str, query: str) -> str:
    """Search for text within a doc. Returns matching text snippets and locations.
    Limitation: Full-text search requires iterating content; returns simplified matches."""
    try:
        data = read_doc(doc_id)
        text = data.get("text", "")
        if not text:
            for tab in data.get("tabs", []):
                text += tab.get("text", "") + "\n"
        query_lower = query.lower()
        matches = []
        for i, line in enumerate(text.split("\n")):
            if query_lower in line.lower():
                matches.append({"line": i + 1, "snippet": line.strip()[:200]})
        return json.dumps({"documentId": doc_id, "query": query, "matches": matches[:20]})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_insert_person(doc_id: str, email: str, index: int = 1, tab_id: str = "") -> str:
    """Insert a person chip (@mention) at the given index. tab_id: optional.
    Limitation: Person chips require People API; may fail with API nuances."""
    err = policy.gate_write("insert_person", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        req: dict[str, Any] = {
            "insertPerson": {
                "location": {"index": index},
                "personProperties": {"email": email},
            }
        }
        if tab_id:
            req["insertPerson"]["location"]["tabId"] = tab_id
        resp = policy.api(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            {"requests": [req]},
        )
        if "error" in resp:
            if tab_id and policy.is_missing_target_error(resp):
                return json.dumps({"status": "not_found", "documentId": doc_id, "tabId": tab_id})
            return json.dumps(resp)
        return json.dumps({
            "status": "inserted",
            "documentId": doc_id,
            "email": email,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        })
    except Exception as e:
        return json.dumps({"error": str(e), "hint": "Person chips may require People API scope"})


# --- Phase 5: image upload and inline insert ---

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


@mcp.tool
def gdocs_upload_image(doc_id: str, local_path: str) -> str:
    """Upload a local image to Drive (co-located with the doc) and grant public read access.

    Supported extensions: .png, .jpg, .jpeg, .webp.
    Returns JSON: {ok, file_id, url, mime_type} on success or {ok, error} on failure.
    """
    ext = os.path.splitext(local_path)[1].lower()
    mime_type = _MIME_BY_EXT.get(ext)
    if mime_type is None:
        return json.dumps({
            "ok": False,
            "error": f"Unsupported file extension '{ext}'. Supported: .png, .jpg, .jpeg, .webp",
        })

    if not os.path.exists(local_path):
        return json.dumps({
            "ok": False,
            "error": f"File not found: {local_path}",
        })

    try:
        with open(local_path, "rb") as f:
            file_bytes = f.read()
    except OSError as e:
        return json.dumps({"ok": False, "error": f"Cannot read file: {e}"})

    parent_folder = policy.doc_parent_folder(doc_id)
    metadata: dict[str, Any] = {"name": os.path.basename(local_path)}
    if parent_folder:
        metadata["parents"] = [parent_folder]

    upload_url = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
    try:
        resp = policy.multipart_upload(upload_url, metadata, file_bytes, mime_type)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Upload failed: {e}"})

    if "error" in resp or "id" not in resp:
        return json.dumps({"ok": False, "error": str(resp)})

    file_id = resp["id"]

    # Grant public reader permission so Docs API can fetch the image URL
    try:
        policy.api(
            "POST",
            f"https://www.googleapis.com/drive/v3/files/{file_id}/permissions",
            {"role": "reader", "type": "anyone"},
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": f"Permission grant failed: {e}"})

    return json.dumps({
        "ok": True,
        "file_id": file_id,
        "url": f"https://drive.google.com/uc?id={file_id}",
        "mime_type": mime_type,
    })


@mcp.tool
def gdocs_insert_image(
    doc_id: str,
    tab_id: str,
    image_url: str,
    index: int,
    width_pt: Optional[float] = None,
    height_pt: Optional[float] = None,
) -> str:
    """Insert an inline image into a specific tab at the given index.

    image_url: publicly accessible URL (e.g. from gdocs_upload_image).
    index: document index position for insertion.
    width_pt / height_pt: optional dimensions in points; omit for intrinsic size.
    Returns the Docs API batchUpdate response JSON as a string.
    """
    err = policy.gate_write("insert_image", doc_id)
    if err:
        return json.dumps({"error": err})

    inline_image: dict[str, Any] = {
        "location": {"index": index, "tabId": tab_id},
        "uri": image_url,
    }
    if width_pt is not None or height_pt is not None:
        inline_image["objectSize"] = {
            "width": {"magnitude": width_pt, "unit": "PT"},
            "height": {"magnitude": height_pt, "unit": "PT"},
        }

    try:
        resp = policy.api(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            {"requests": [{"insertInlineImage": inline_image}]},
        )
        if policy.is_missing_target_error(resp):
            return json.dumps({"status": "not_found", "documentId": doc_id, "tabId": tab_id})
        return json.dumps(resp, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})
