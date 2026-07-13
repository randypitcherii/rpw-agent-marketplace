"""
Write-path operations for the Google Docs MCP server.

Document lifecycle (``create_doc`` / ``update_doc`` / ``delete_doc``), tabs
(``add_tab``, ``clear_tab_content``, ``write_to_tab``), and ``find_replace``.
Content insertion delegates to ``markdown_render._insert_markdown``; tab lookups
use the recursive ``tabs._find_tab_by_id``. All Google calls route through
``auth`` (module-qualified for a single test patch point).
"""

import subprocess
from typing import Any, Dict, List, Optional

import auth
import config
from markdown_inline import _mk_range
from markdown_render import _insert_markdown
from tabs import _find_tab_by_id


def _collect_tab_image_object_ids(tab: Dict[str, Any]) -> List[str]:
    """Return the inlineObjectIds of every embedded image in a tab's body.

    Walks paragraphs and recurses into table cells — an image lives inside a
    paragraph's ``inlineObjectElement``, and Docs nests tables' cell content the
    same way the body does (#311). These object IDs are what ``gdocs_get_image``
    resolves, so the refusal can name exactly what a clear would destroy.
    """
    ids: List[str] = []

    def _walk(content: List[Dict[str, Any]]) -> None:
        for element in content:
            if "paragraph" in element:
                for pe in element["paragraph"].get("elements", []):
                    ioe = pe.get("inlineObjectElement")
                    if ioe and ioe.get("inlineObjectId"):
                        ids.append(ioe["inlineObjectId"])
            elif "table" in element:
                for row in element["table"].get("tableRows", []):
                    for cell in row.get("tableCells", []):
                        _walk(cell.get("content", []))

    _walk(tab.get("documentTab", {}).get("body", {}).get("content", []))
    return ids


def _image_destruction_refusal(doc_id: str, tab_id: str, image_ids: List[str]) -> Dict[str, Any]:
    """Structured, actionable refusal returned when a clear would destroy images.

    Names the image objectIds and the round-trip workaround tools so an agent can
    recover (rather than silently losing embedded images, per #311). Includes an
    ``error`` key so the refusal fails closed through every caller that short-
    circuits on errors, and a distinct ``status`` for callers that branch on it.
    """
    return {
        "status": "blocked_image_destruction",
        "documentId": doc_id,
        "tabId": tab_id,
        "imageObjectIds": image_ids,
        "error": (
            f"Refusing to clear tab {tab_id}: it contains {len(image_ids)} embedded "
            f"image(s) ({', '.join(image_ids)}) that clearing would permanently destroy "
            "(Google Docs cannot re-anchor an image once its bytes are gone). To preserve "
            "them, read each with gdocs_get_image(doc_id, object_id), then after your write "
            "re-upload via gdocs_upload_image and re-insert via gdocs_insert_image. To clear "
            "anyway and lose these images, re-run with allow_image_destruction=True."
        ),
    }


def create_doc(title: str, content: Optional[str] = None) -> Dict:
    """Create a new Google Doc in the target folder."""
    if not config.TARGET_FOLDER_ID:
        raise RuntimeError(
            "GDOCS_TARGET_FOLDER_ID is not set — set the env var or use run_mcp.py for env-file resolution"
        )
    # Step 1: Create the doc via Docs API
    resp = auth.api("POST", "https://docs.googleapis.com/v1/documents", {"title": title})
    if "error" in resp:
        return resp
    doc_id = resp["documentId"]

    # Step 2: Move it into the target folder via Drive API
    token = auth.get_token()
    # Get current parent
    file_info = auth.api("GET", f"https://www.googleapis.com/drive/v3/files/{doc_id}?fields=parents")
    current_parents = ",".join(file_info.get("parents", []))

    # Move to target folder
    move_cmd = [
        "curl", "-s", "-X", "PATCH",
        f"https://www.googleapis.com/drive/v3/files/{doc_id}?addParents={config.TARGET_FOLDER_ID}&removeParents={current_parents}",
        "-H", f"Authorization: Bearer {token}",
        "-H", f"x-goog-user-project: {config.QUOTA_PROJECT}",
        "-H", "Content-Type: application/json",
    ]
    subprocess.run(move_cmd, capture_output=True, text=True)

    # Step 3: Add content if provided
    if content:
        _insert_markdown(doc_id, content, index=1)

    return {
        "documentId": doc_id,
        "title": title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def update_doc(doc_id: str, content: str) -> Dict:
    """Append markdown-ish content to the end of a document."""
    # Get end index
    resp = auth.api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}")
    if "error" in resp:
        return resp
    body_content = resp.get("body", {}).get("content", [])
    end_index = body_content[-1].get("endIndex", 1) - 1 if body_content else 1

    _insert_markdown(doc_id, content, index=end_index)
    return {
        "status": "updated",
        "documentId": doc_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def delete_doc(doc_id: str) -> Dict:
    """Trash a document (soft delete)."""
    resp = auth.api(
        "PATCH",
        f"https://www.googleapis.com/drive/v3/files/{doc_id}",
        {"trashed": True},
    )
    if "error" in resp:
        return resp
    return {"status": "trashed", "documentId": doc_id}


def add_tab(doc_id: str, tab_name: str, content: Optional[str] = None,
            parent_tab_id: Optional[str] = None, icon_emoji: Optional[str] = None) -> Dict:
    """Add a named tab (or sub-tab if parent_tab_id is given) to a Google Doc."""
    tab_props: Dict[str, Any] = {"title": tab_name}
    if parent_tab_id:
        tab_props["parentTabId"] = parent_tab_id
    if icon_emoji:
        tab_props["iconEmoji"] = icon_emoji

    requests = [
        {
            "addDocumentTab": {
                "tabProperties": tab_props,
            }
        }
    ]
    resp = auth.api(
        "POST",
        f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
        {"requests": requests},
    )
    if "error" in resp:
        return resp

    # Extract the new tab ID from the response
    new_tab_id = None
    replies = resp.get("replies", [])
    for reply in replies:
        if "addDocumentTab" in reply:
            new_tab_id = reply["addDocumentTab"].get("tabProperties", {}).get("tabId")
            break

    result = {
        "status": "tab_added",
        "documentId": doc_id,
        "tabName": tab_name,
        "tabId": new_tab_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }

    # Add content to the new tab if provided
    if content and new_tab_id:
        _insert_markdown(doc_id, content, index=1, tab_id=new_tab_id)

    return result


def find_replace(doc_id: str, find_text: str, replace_text: str,
                 match_case: bool = False, tab_id: Optional[str] = None) -> Dict:
    """Replace all occurrences of find_text with replace_text in a doc (optionally in a tab)."""
    req: Dict[str, Any] = {
        "replaceAllText": {
            "containsText": {"text": find_text, "matchCase": match_case},
            "replaceText": replace_text,
        }
    }
    if tab_id:
        req["replaceAllText"]["tabsCriteria"] = {"tabIds": [tab_id]}
    resp = auth.api(
        "POST",
        f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
        {"requests": [req]},
    )
    if "error" in resp:
        return resp
    count = resp.get("replies", [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
    return {
        "status": "replaced",
        "documentId": doc_id,
        "occurrencesChanged": count,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def clear_tab_content(doc_id: str, tab_id: str, allow_image_destruction: bool = False) -> Dict:
    """Delete all body content from a tab, leaving the (empty) trailing paragraph.

    Returns a status dict: ``cleared`` (content deleted), ``already_empty`` (nothing
    to delete), ``not_found`` (tab absent), ``blocked_image_destruction`` (tab holds
    embedded images and ``allow_image_destruction`` is False — the default), or an
    ``error`` envelope on API failure.

    Embedded inline images are permanently destroyed by the clear+rebuild (#311) and
    cannot be re-anchored afterward, so by default a tab containing images is refused
    with a structured, actionable error naming the objectIds and the round-trip tools.
    Pass ``allow_image_destruction=True`` to clear anyway.

    Note: Google Docs has no ``deleteList`` request. The trailing paragraph that is
    deliberately kept here still references its own bullet if the tab was left in a
    list state, so re-inserting into it (``_insert_markdown(index=1)``) would make
    every inserted paragraph inherit that bullet. That inheritance is cleared on the
    insert side: ``markdown_render`` emits ``deleteParagraphBullets`` over each
    non-list paragraph range (#301), so a leftover anchor bullet no longer bleeds
    into headings/normal paragraphs regardless of the tab's prior state.
    """
    doc = auth.api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true")
    if "error" in doc:
        return doc

    tab = _find_tab_by_id(doc.get("tabs", []), tab_id)
    if tab is None:
        return {"status": "not_found", "documentId": doc_id, "tabId": tab_id}

    # Refuse-by-default guard (#311): clearing destroys embedded images irrecoverably.
    if not allow_image_destruction:
        image_ids = _collect_tab_image_object_ids(tab)
        if image_ids:
            return _image_destruction_refusal(doc_id, tab_id, image_ids)

    body_content = tab.get("documentTab", {}).get("body", {}).get("content", [])
    # A tab with only the trailing paragraph (1 element) has nothing to delete.
    if len(body_content) <= 1:
        return {"status": "already_empty", "documentId": doc_id, "tabId": tab_id}

    # Delete from after the first element (section break) up to the trailing paragraph.
    start_idx = body_content[0].get("endIndex", 1)
    end_idx = body_content[-1].get("endIndex", start_idx + 1) - 1
    if start_idx >= end_idx:
        return {"status": "already_empty", "documentId": doc_id, "tabId": tab_id}

    # After deleting [start_idx, end_idx), the trailing paragraph's newline shifts
    # down to occupy [start_idx, start_idx + 1). Reset its bullet + named style in
    # the SAME batch (#301): the tab may have been left in a list state, and the
    # trailing paragraph still references its bullet. _insert_markdown(index=1)
    # then splits that anchor, so without this reset every inserted paragraph —
    # and the empty structural paragraphs Docs adds around tables — inherits the
    # bullet. Clearing it here is the anchor-side half of the #301 fix, mirroring
    # the emit-side deleteParagraphBullets in markdown_render.
    trailing = _mk_range(start_idx, start_idx + 1, tab_id)
    resp = auth.api(
        "POST",
        f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
        {"requests": [
            {"deleteContentRange": {"range": _mk_range(start_idx, end_idx, tab_id)}},
            {"deleteParagraphBullets": {"range": trailing}},
            {"updateParagraphStyle": {
                "range": trailing,
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                "fields": "namedStyleType",
            }},
        ]},
    )
    if "error" in resp:
        return resp
    return {"status": "cleared", "documentId": doc_id, "tabId": tab_id}


def write_to_tab(doc_id: str, tab_id: str, content: str,
                 code_font: str = config.DEFAULT_CODE_FONT, bullet_preset: str = "",
                 allow_image_destruction: bool = False) -> Dict:
    """Replace a tab's content with rendered markdown.

    Idempotent: the tab is cleared before inserting, so re-running with the same content
    yields the same visible document instead of prepending a second copy. Returns
    ``not_found`` if the tab does not exist (nothing is inserted).

    bullet_preset: optional Docs API bulletPreset for unordered lists (#170). Empty =
    default disc. Validated at this boundary so an unknown value returns a clean error
    BEFORE the tab is cleared, rather than leaking a Google 400 mid-write.

    allow_image_destruction: if the target tab contains embedded images, the clear
    step refuses by default with ``blocked_image_destruction`` (nothing is written),
    since the rebuild would destroy them irrecoverably (#311). Pass True to overwrite
    anyway.
    """
    if bullet_preset and bullet_preset not in config.VALID_BULLET_PRESETS:
        return {
            "error": (
                f"Invalid bullet_preset '{bullet_preset}'. "
                f"Valid presets: {', '.join(sorted(config.VALID_BULLET_PRESETS))}"
            )
        }
    cleared = clear_tab_content(doc_id, tab_id, allow_image_destruction=allow_image_destruction)
    if cleared.get("status") == "not_found":
        return {"status": "not_found", "documentId": doc_id, "tabId": tab_id}
    if cleared.get("status") == "blocked_image_destruction":
        return cleared
    if "error" in cleared:
        return cleared
    _insert_markdown(doc_id, content, index=1, tab_id=tab_id, code_font=code_font,
                     bullet_preset=bullet_preset)
    return {
        "status": "written",
        "documentId": doc_id,
        "tabId": tab_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }
