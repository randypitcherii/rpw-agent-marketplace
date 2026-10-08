"""
Write-path operations for the Google Docs MCP server.

Document lifecycle (``create_doc`` / ``update_doc`` / ``delete_doc``), tabs
(``add_tab``, ``clear_tab_content``, ``write_to_tab``), and ``find_replace``.
Content insertion delegates to ``markdown_render._insert_markdown``; tab lookups
use the recursive ``tabs._find_tab_by_id``. All Google calls route through
``auth`` (module-qualified for a single test patch point).
"""

from typing import Any, Dict, List, Optional

import auth
import config
from markdown_inline import _mk_range
from markdown_render import _insert_markdown
from tabs import _find_tab_by_id


def _insert_failure_details(insert_result: Dict) -> Dict[str, Any]:
    """Extract the failure fields from an ``_insert_markdown`` envelope (#423)."""
    return {
        "insertError": insert_result.get("error"),
        "apiError": insert_result.get("apiError"),
        "batchesCompleted": insert_result.get("batchesCompleted", 0),
    }


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
    """Create a new Google Doc in the target folder.

    Returns a status envelope (#421/#423 — partial failures are surfaced, not
    swallowed):
      - ``created`` — doc created, moved into the target folder, content (if any) inserted.
      - ``created_but_move_failed`` — doc exists but is in the Drive root; the move
        into GDOCS_TARGET_FOLDER_ID failed (``moveError`` has the detail).
      - ``created_but_content_failed`` — doc created (and moved) but the content
        insert failed; the doc may be empty or partially written.
      - ``created_but_move_and_content_failed`` — both of the above.
    Partial-failure envelopes carry an ``error`` message so callers that
    short-circuit on errors fail closed, plus the ``documentId``/``url`` since
    the doc does exist.

    GDOCS_TARGET_FOLDER_ID is optional: when it is unset the move step is
    skipped entirely and the doc lives in the Drive root — that is plain
    ``created``, not a failure.
    """
    # Step 1: Create the doc via Docs API
    resp = auth.api("POST", "https://docs.googleapis.com/v1/documents", {"title": title})
    if "error" in resp:
        return resp
    doc_id = resp["documentId"]

    result: Dict[str, Any] = {
        "status": "created",
        "documentId": doc_id,
        "title": title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }

    # Step 2: Move it into the target folder via Drive API — only when a target
    # folder is configured (GDOCS_TARGET_FOLDER_ID is optional; unset = the doc
    # stays in the Drive root, no move attempted). A failed move used to be
    # silently ignored (curl result discarded), leaving the doc in the Drive
    # root while the tool reported unqualified success (#421).
    move_failed = False
    if config.TARGET_FOLDER_ID:
        file_info = auth.api("GET", f"https://www.googleapis.com/drive/v3/files/{doc_id}?fields=parents")
        current_parents = ",".join(file_info.get("parents", [])) if "error" not in file_info else ""
        move_resp = auth.api(
            "PATCH",
            f"https://www.googleapis.com/drive/v3/files/{doc_id}"
            f"?addParents={config.TARGET_FOLDER_ID}&removeParents={current_parents}",
        )
        move_failed = isinstance(move_resp, dict) and "error" in move_resp
        if move_failed:
            move_err = move_resp.get("error")
            move_msg = move_err.get("message") if isinstance(move_err, dict) else str(move_err)
            result["moveError"] = move_err

    # Step 3: Add content if provided
    insert_failed = False
    if content:
        inserted = _insert_markdown(doc_id, content, index=1)
        insert_failed = inserted.get("status") != "inserted"
        if insert_failed:
            result.update(_insert_failure_details(inserted))

    if move_failed and insert_failed:
        result["status"] = "created_but_move_and_content_failed"
        result["error"] = (
            f"Doc {doc_id} was created but is in the Drive root (move into folder "
            f"{config.TARGET_FOLDER_ID} failed: {move_msg}) AND the content insert failed "
            f"({result.get('insertError')}); the doc may be empty or partially written."
        )
    elif move_failed:
        result["status"] = "created_but_move_failed"
        result["error"] = (
            f"Doc {doc_id} was created but the move into folder {config.TARGET_FOLDER_ID} "
            f"failed — it is in the Drive root, NOT the target folder: {move_msg}"
        )
    elif insert_failed:
        result["status"] = "created_but_content_failed"
        result["error"] = (
            f"Doc {doc_id} was created in the target folder but the content insert failed; "
            f"the doc may be empty or partially written: {result.get('insertError')}"
        )
    return result


def update_doc(doc_id: str, content: str) -> Dict:
    """Append markdown-ish content to the end of a document.

    Returns ``status: updated`` only when every insert batch succeeded (#423);
    on insert failure returns ``status: update_failed`` with the API error detail
    (the append is non-destructive, but the content may be partially written).
    """
    # Get end index
    resp = auth.api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}")
    if "error" in resp:
        return resp
    body_content = resp.get("body", {}).get("content", [])
    end_index = body_content[-1].get("endIndex", 1) - 1 if body_content else 1

    inserted = _insert_markdown(doc_id, content, index=end_index)
    if inserted.get("status") != "inserted":
        return {
            "status": "update_failed",
            "documentId": doc_id,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
            "error": (
                f"Appending content to doc {doc_id} failed; the content may be "
                f"partially written: {inserted.get('error')}"
            ),
            **_insert_failure_details(inserted),
        }
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
            parent_tab_id: Optional[str] = None, icon_emoji: Optional[str] = None,
) -> Dict:
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

    # Add content to the new tab if provided. Surface an insert failure instead
    # of reporting an unqualified tab_added (#423): the tab exists, but its
    # content may be missing or partial.
    if content and new_tab_id:
        inserted = _insert_markdown(doc_id, content, index=1, tab_id=new_tab_id)
        if inserted.get("status") != "inserted":
            result["status"] = "tab_added_but_content_failed"
            result["error"] = (
                f"Tab {new_tab_id} was added but writing its content failed; the tab "
                f"may be empty or partially written: {inserted.get('error')}"
            )
            result.update(_insert_failure_details(inserted))

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
                 allow_image_destruction: bool = False) -> Dict:
    """Replace a tab's content with rendered markdown.

    Idempotent: the tab is cleared before inserting, so re-running with the same content
    yields the same visible document instead of prepending a second copy. Returns
    ``not_found`` if the tab does not exist (nothing is inserted).

    allow_image_destruction: if the target tab contains embedded images, the clear
    step refuses by default with ``blocked_image_destruction`` (nothing is written),
    since the rebuild would destroy them irrecoverably (#311). Pass True to overwrite
    anyway.

    Error handling (#423): ``written`` is returned ONLY when every insert batch
    succeeded. Because the tab is cleared before inserting, an insert failure is
    destructive — the previous content is already gone — so it is reported as an
    explicit ``status: cleared_but_write_failed`` envelope naming the loss (with the
    Google API error and how many batches landed), never as success.
    """
    cleared = clear_tab_content(doc_id, tab_id, allow_image_destruction=allow_image_destruction)
    if cleared.get("status") == "not_found":
        return {"status": "not_found", "documentId": doc_id, "tabId": tab_id}
    if cleared.get("status") == "blocked_image_destruction":
        return cleared
    if "error" in cleared:
        return cleared
    inserted = _insert_markdown(doc_id, content, index=1, tab_id=tab_id)
    if inserted.get("status") != "inserted":
        # Fail closed on the destructive ordering: the clear already ran, so the
        # tab's previous content is gone and the new content is absent or partial.
        # Name the loss explicitly instead of stamping "written" (#423).
        batches_done = inserted.get("batchesCompleted", 0)
        return {
            "status": "cleared_but_write_failed",
            "documentId": doc_id,
            "tabId": tab_id,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
            "error": (
                f"Tab {tab_id} was cleared but inserting the new content failed after "
                f"{batches_done} successful batch(es) — the tab's previous content is lost "
                f"and it is now {'partially written' if batches_done else 'empty'}. "
                f"Re-run the write or restore from your source. Insert error: "
                f"{inserted.get('error')}"
            ),
            **_insert_failure_details(inserted),
        }
    return {
        "status": "written",
        "documentId": doc_id,
        "tabId": tab_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }
