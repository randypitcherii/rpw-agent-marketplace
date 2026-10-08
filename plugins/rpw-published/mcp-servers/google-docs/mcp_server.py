#!/usr/bin/env python3
"""
Google Docs with Subtabs MCP Server.

Exposes tools for CRUD, tabs, find/replace, tab-targeted write, and phase 4/5
operations. Enforces read-only mode, folder allow-list, and audit logging.

Layout (post-#318 restructure):
  - ``app``           — the shared FastMCP instance
  - this module       — core CRUD + tab-lifecycle tools, plus the entrypoint
  - ``tools_media``   — slides read/create/replace + share/search/person + image
  - ``tools_sheets``  — Google Sheets (API v4) values read/write/append/clear/format
  - ``tools_slides``  — Slides template-fill: copy-template + batch replace/table/image
  - ``policy``        — read-only/allow-list/audit gating + API error mapping
  - ``docs_read`` / ``docs_write`` / ``markdown_render`` / ``markdown_inline`` /
    ``tabs`` / ``auth`` / ``config`` — the underlying library
"""

import json

import auth
import policy
import style_gate
import style_lint
from app import mcp
from docs_read import get_image_bytes, list_docs, read_doc
from docs_write import (
    add_tab,
    clear_tab_content as _clear_tab_content,
    create_doc,
    delete_doc,
    find_replace as _find_replace,
    update_doc,
    write_to_tab as _write_to_tab,
)

# Backwards-compatible aliases for the safety helpers, re-exported so callers and
# tests that reference them on this module keep working after the policy split.
is_read_only = policy.is_read_only
is_folder_allowed = policy.is_folder_allowed


# --- Phase 1: MVP tools ---

@mcp.tool
def gdocs_list() -> str:
    """List Google Docs — the target folder when GDOCS_TARGET_FOLDER_ID is set, else your 50 most
    recently modified Docs across Drive. Returns JSON with id, name, modifiedTime, webViewLink."""
    try:
        out = list_docs()
        return json.dumps({"files": out}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_read(doc_id: str) -> str:
    """Read a doc's content (text and tabs). doc_id: Google Doc ID from URL."""
    try:
        out = read_doc(doc_id)
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_lint(doc_id: str, tab_id: str = "") -> str:
    """Check a doc against the house style (house_style.json) in code — no content read-back.

    Use this after any Docs write instead of reading the doc to eyeball formatting.
    tab_id: optional; omit to lint every tab (child tabs included).
    Returns { ok, errors, warnings, checked, by_rule, violations[] }: violations are grouped by
    (rule, expected, actual) with a count and at most two short location samples. ok is false only
    on errors; warnings (e.g. non-dash bullet glyphs, which the API cannot create) never block.
    """
    try:
        resp = auth.api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true")
        if "error" in resp:
            return json.dumps(resp)
        out = style_lint.lint_document(resp, tab_id=tab_id or None)
        return json.dumps({"documentId": doc_id, **out}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_get_image(doc_id: str, object_id: str) -> str:
    """Fetch the bytes of an inline image as base64.

    Use gdocs_read first to discover objectIds (look for [image: <objectId>] placeholders).
    Returns: { documentId, objectId, mimeType, data } where data is base64.
    On missing objectId: { status: "not_found", ... }.
    """
    import json
    try:
        return json.dumps(get_image_bytes(doc_id, object_id))
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_create(title: str, content: str = "") -> str:
    """Create a new doc in the target folder. content: optional markdown.


    Returns status "created" only when the doc was created, moved into
    GDOCS_TARGET_FOLDER_ID (when one is configured — the folder is optional;
    unset means the doc stays in the Drive root and no move is attempted),
    and any content was fully inserted. Partial failures
    are surfaced instead of silent success: "created_but_move_failed" (doc exists
    but landed in the Drive root — moveError has the Drive error),
    "created_but_content_failed" (doc created/moved but the markdown insert
    failed; doc may be empty or partial), or "created_but_move_and_content_failed".
    Those envelopes still include documentId/url since the doc exists.

    House style (#2001): after a successful write the tab is normalized to
    house_style.json and linted in code. The result carries a compact "style"
    summary ({ok, errors, warnings, by_rule, samples, normalized}); if errors remain,
    the status gets a "_but_style_check_failed" suffix and "error" is set. Do not
    read the doc back to check formatting.
    """
    err = policy.gate_write("create", "new")
    if err:
        return json.dumps({"error": err})
    try:
        out = create_doc(title, content or None)
        # Audit whenever a doc actually got created (documentId present) — partial
        # failures like created_but_move_failed still created a real doc.
        if out.get("documentId"):
            policy.append_audit("create", out.get("documentId", ""), f"title={title}")
        if out.get("status") == "created":
            out = style_gate.gate(out, out["documentId"])
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_update(doc_id: str, content: str) -> str:
    """Append markdown content to the end of a doc.


    Returns status "updated" only when every insert batch succeeded; on API
    failure returns "update_failed" with the Google error (the append is
    non-destructive, but content may be partially written).

    House style (#2001): after a successful write the doc's first tab (where the append lands) is normalized to
    house_style.json and linted in code. The result carries a compact "style"
    summary ({ok, errors, warnings, by_rule, samples, normalized}); if errors remain,
    the status gets a "_but_style_check_failed" suffix and "error" is set. Do not
    read the doc back to check formatting.
    """
    err = policy.gate_write("update", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = update_doc(doc_id, content)
        if "error" not in out:
            policy.append_audit("update", doc_id, "")
        if out.get("status") == "updated":
            out = style_gate.gate(out, doc_id)
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_delete(doc_id: str) -> str:
    """Trash (soft delete) a doc."""
    err = policy.gate_write("delete", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = delete_doc(doc_id)
        if "error" not in out:
            policy.append_audit("delete", doc_id, "")
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_add_tab(
    doc_id: str,
    tab_name: str,
    content: str = "",
    parent_tab_id: str = "",
    icon_emoji: str = "",
) -> str:
    """Add a tab (or sub-tab) to a doc. parent_tab_id: optional for nesting. icon_emoji: optional emoji.

    Returns status "tab_added" only when the tab was created and any content was
    fully inserted; if the content insert fails, returns
    "tab_added_but_content_failed" (tab exists but may be empty or partially
    written) with the Google API error.

    House style (#2001): after a successful write the new tab is normalized to
    house_style.json and linted in code. The result carries a compact "style"
    summary ({ok, errors, warnings, by_rule, samples, normalized}); if errors remain,
    the status gets a "_but_style_check_failed" suffix and "error" is set. Do not
    read the doc back to check formatting.
    """
    err = policy.gate_write("add_tab", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = add_tab(
            doc_id,
            tab_name,
            content or None,
            parent_tab_id=parent_tab_id or None,
            icon_emoji=icon_emoji or None,
        )
        if parent_tab_id and policy.is_missing_target_error(out):
            return json.dumps({"status": "not_found", "documentId": doc_id, "parentTabId": parent_tab_id})
        # Audit whenever the tab itself was created — including the partial
        # tab_added_but_content_failed case (the mutation happened).
        if str(out.get("status", "")).startswith("tab_added"):
            policy.append_audit("add_tab", doc_id, f"tab={tab_name}")
        if out.get("status") == "tab_added" and out.get("tabId"):
            out = style_gate.gate(out, doc_id, out["tabId"])
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Phase 2: find/replace, tab-targeted write ---

@mcp.tool
def gdocs_find_replace(
    doc_id: str,
    find_text: str,
    replace_text: str,
    match_case: bool = False,
    tab_id: str = "",
) -> str:
    """Replace all occurrences of find_text with replace_text. tab_id: optional to scope to one tab.

    Not house-style gated: replaced text keeps the style of the text it replaces
    (see style_gate.py). Run gdocs_lint afterwards if the tab's formatting matters.
    """
    err = policy.gate_write("find_replace", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = _find_replace(
            doc_id,
            find_text,
            replace_text,
            match_case=match_case,
            tab_id=tab_id or None,
        )
        if tab_id and policy.is_missing_target_error(out):
            return json.dumps({"status": "not_found", "documentId": doc_id, "tabId": tab_id})
        if "error" not in out:
            policy.append_audit("find_replace", doc_id, f"find={find_text[:50]}")
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_write_to_tab(doc_id: str, tab_id: str, content: str,
                       allow_image_destruction: bool = False) -> str:
    """Replace a tab's content with rendered markdown (idempotent).

    The tab is cleared before inserting, so re-running with the same content yields the
    same document instead of a second prepended copy. Returns not_found if the tab does
    not exist.

    Embedded images in the target tab are permanently destroyed by the clear+rebuild and
    cannot be re-anchored afterward (#311). By default this refuses (status
    blocked_image_destruction, nothing written) and names the image objectIds plus the
    gdocs_get_image / gdocs_upload_image / gdocs_insert_image round-trip. Pass
    allow_image_destruction=True to overwrite anyway.

    Status "written" is returned ONLY when every insert batch succeeded — Google API
    errors are propagated, not swallowed. Because the tab is cleared before inserting,
    an insert failure is destructive: it is reported as status
    "cleared_but_write_failed" (previous content lost; tab empty or partially written,
    with the Google error and batchesCompleted), never as success. Transient 429
    rate-limit errors are retried with backoff before failing.

    House style (#2001): after a successful write the tab is normalized to
    house_style.json and linted in code. The result carries a compact "style"
    summary ({ok, errors, warnings, by_rule, samples, normalized}); if errors remain,
    the status gets a "_but_style_check_failed" suffix and "error" is set. Do not
    read the doc back to check formatting.
"""
    err = policy.gate_write("write_to_tab", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = _write_to_tab(doc_id, tab_id, content,
                            allow_image_destruction=allow_image_destruction)
        if out.get("status") == "written":
            policy.append_audit("write_to_tab", doc_id, f"tab={tab_id}")
            out = style_gate.gate(out, doc_id, tab_id)
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Phase 5b: Tab lifecycle — delete, clear, rename ---

@mcp.tool
def gdocs_delete_tab(doc_id: str, tab_id: str) -> str:
    """Delete a tab from a document. Idempotent: returns not_found (not an error) if tab is missing.

    doc_id: Google Doc ID.
    tab_id: Tab ID to delete (e.g. t.abc123).
    """
    err = policy.gate_write("delete_tab", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        resp = policy.api(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            {"requests": [{"deleteTab": {"tabId": tab_id}}]},
        )
        if "error" in resp:
            if policy.is_missing_target_error(resp):
                return json.dumps({"status": "not_found", "documentId": doc_id, "tabId": tab_id})
            return json.dumps(resp)
        policy.append_audit("delete_tab", doc_id, f"tab={tab_id}")
        return json.dumps({"status": "deleted", "documentId": doc_id, "tabId": tab_id})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_clear_tab(doc_id: str, tab_id: str, allow_image_destruction: bool = False) -> str:
    """Clear all content from a tab, leaving the tab itself present and empty.

    Idempotent: returns already_empty if tab has no deletable content, not_found if tab
    doesn't exist in the document.

    doc_id: Google Doc ID.
    tab_id: Tab ID to clear.

    Embedded images are permanently destroyed by clearing and cannot be re-anchored
    afterward (#311). By default this refuses (status blocked_image_destruction) and
    names the image objectIds plus the gdocs_get_image / gdocs_upload_image /
    gdocs_insert_image round-trip. Pass allow_image_destruction=True to clear anyway.
    """
    err = policy.gate_write("clear_tab", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        # Delegate the GET + deleteContentRange to the shared helper so write_to_tab's
        # idempotent clear and this tool stay in lockstep (single source of truth).
        result = _clear_tab_content(doc_id, tab_id, allow_image_destruction=allow_image_destruction)
        if "error" in result:
            return json.dumps(result)
        if result.get("status") == "cleared":
            policy.append_audit("clear_tab", doc_id, f"tab={tab_id}")
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_rename_tab(doc_id: str, tab_id: str, new_title: str) -> str:
    """Rename a tab in a document. Idempotent: returns not_found if tab is missing.

    doc_id: Google Doc ID.
    tab_id: Tab ID to rename.
    new_title: New title for the tab.
    """
    err = policy.gate_write("rename_tab", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        resp = policy.api(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            {
                "requests": [
                    {
                        "updateDocumentTabProperties": {
                            "tabProperties": {"tabId": tab_id, "title": new_title},
                            "fields": "title",
                        }
                    }
                ]
            },
        )
        if "error" in resp:
            if policy.is_missing_target_error(resp):
                return json.dumps({"status": "not_found", "documentId": doc_id, "tabId": tab_id})
            return json.dumps(resp)
        policy.append_audit("rename_tab", doc_id, f"tab={tab_id} new_title={new_title}")
        return json.dumps({
            "status": "renamed",
            "documentId": doc_id,
            "tabId": tab_id,
            "newTitle": new_title,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


# Register the media + collaboration tools (slides/share/search/person + image
# upload/insert) on the shared `mcp` instance, and re-export them here so callers
# and tests that reference them as `mcp_server.<tool>` keep resolving.
from tools_media import (  # noqa: E402
    gdocs_insert_image,
    gdocs_insert_person,
    gdocs_search,
    gdocs_share,
    gdocs_slides_create,
    gdocs_slides_metadata,
    gdocs_slides_read,
    gdocs_slides_replace_text,
    gdocs_upload_image,
)

# Register the Google Sheets (API v4) tools on the shared `mcp` instance and
# re-export them here so `mcp_server.<tool>` resolution works (mirrors tools_media).
from tools_sheets import (  # noqa: E402
    gsheets_append_rows,
    gsheets_clear,
    gsheets_format,
    gsheets_read_values,
    gsheets_write_values,
)

# Register the Google Slides template-fill tools (copy-template + batch
# replace/table-fill/image-insert) on the shared `mcp` instance and re-export
# them here so `mcp_server.<tool>` resolution works (mirrors tools_media, #196).
from tools_slides import (  # noqa: E402
    gdocs_slides_copy_template,
    gdocs_slides_fill_table,
    gdocs_slides_insert_image,
    gdocs_slides_replace_all_text,
)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
