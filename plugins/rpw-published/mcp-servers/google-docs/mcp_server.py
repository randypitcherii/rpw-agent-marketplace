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

import policy
from app import mcp
from config import DEFAULT_CODE_FONT
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
    """List Google Docs in the target folder. Returns JSON with id, name, modifiedTime, webViewLink."""
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
    """Create a new doc in the target folder. content: optional markdown."""
    err = policy.gate_write("create", "new")
    if err:
        return json.dumps({"error": err})
    try:
        out = create_doc(title, content or None)
        if "error" not in out:
            policy.append_audit("create", out.get("documentId", ""), f"title={title}")
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_update(doc_id: str, content: str) -> str:
    """Append markdown content to the end of a doc."""
    err = policy.gate_write("update", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = update_doc(doc_id, content)
        if "error" not in out:
            policy.append_audit("update", doc_id, "")
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
    """Add a tab (or sub-tab) to a doc. parent_tab_id: optional for nesting. icon_emoji: optional emoji."""
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
        if "error" not in out:
            policy.append_audit("add_tab", doc_id, f"tab={tab_name}")
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
    """Replace all occurrences of find_text with replace_text. tab_id: optional to scope to one tab."""
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
                       code_font: str = "", bullet_preset: str = "",
                       allow_image_destruction: bool = False) -> str:
    """Replace a tab's content with rendered markdown (idempotent).

    The tab is cleared before inserting, so re-running with the same content yields the
    same document instead of a second prepended copy. Returns not_found if the tab does
    not exist. code_font: optional font for code blocks and inline code (default: Courier New).
    bullet_preset: optional Docs API bulletPreset applied to unordered lists, e.g.
    BULLET_ARROW_DIAMOND_DISC (▸), BULLET_CHECKBOX (☐), BULLET_STAR_CIRCLE_SQUARE (★).
    Empty = default disc bullet. An unknown value returns a structured error (the tab is
    not modified). Ordered lists always use the numbered preset and ignore this.

    Embedded images in the target tab are permanently destroyed by the clear+rebuild and
    cannot be re-anchored afterward (#311). By default this refuses (status
    blocked_image_destruction, nothing written) and names the image objectIds plus the
    gdocs_get_image / gdocs_upload_image / gdocs_insert_image round-trip. Pass
    allow_image_destruction=True to overwrite anyway."""
    err = policy.gate_write("write_to_tab", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = _write_to_tab(doc_id, tab_id, content,
                            code_font=code_font or DEFAULT_CODE_FONT,
                            bullet_preset=bullet_preset,
                            allow_image_destruction=allow_image_destruction)
        if out.get("status") == "written":
            policy.append_audit("write_to_tab", doc_id, f"tab={tab_id}")
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
