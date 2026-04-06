#!/usr/bin/env python3
"""
Google Docs with Subtabs MCP Server.

Exposes tools for CRUD, tabs, find/replace, tab-targeted write, and phase 4 operations.
Enforces read-only mode, folder allow-list, and audit logging.
"""

import json
import os
from datetime import datetime
from typing import Any, Optional

from fastmcp import FastMCP

from gdocs_mvp import (
    add_tab,
    create_doc,
    delete_doc,
    find_replace as _find_replace,
    list_docs,
    read_doc,
    update_doc,
    write_to_tab as _write_to_tab,
)
from gdocs_mvp import api as _api

mcp = FastMCP(name="google-docs-with-subtabs")

# --- Config ---
def _read_only() -> bool:
    return os.environ.get("GDOCS_READ_ONLY", "false").lower() in ("1", "true", "yes")


def _allowed_folders() -> list[str]:
    raw = os.environ.get("GDOCS_ALLOWED_FOLDERS", "")
    if not raw:
        return []
    return [f.strip() for f in raw.split(",") if f.strip()]


def _target_folder() -> str:
    return os.environ.get("GDOCS_TARGET_FOLDER_ID", "")


def _audit_log_path() -> Optional[str]:
    return os.environ.get("GDOCS_AUDIT_LOG_PATH")


def _append_audit(op: str, doc_id: str, extra: str = "") -> None:
    path = _audit_log_path()
    if not path:
        return
    line = f"{datetime.utcnow().isoformat()}Z\t{op}\t{doc_id}\t{extra}\n"
    try:
        with open(path, "a") as f:
            f.write(line)
    except OSError:
        pass


def _doc_parent_folder(doc_id: str) -> Optional[str]:
    """Get the parent folder ID of a doc. Returns None if not in a folder."""
    try:
        resp = _api("GET", f"https://www.googleapis.com/drive/v3/files/{doc_id}?fields=parents")
        parents = resp.get("parents", [])
        return parents[0] if parents else None
    except Exception:
        return None


def _check_allow_list(doc_id: str) -> tuple[bool, str]:
    """Returns (allowed, error_msg)."""
    allowed = _allowed_folders()
    if not allowed:
        return True, ""
    parent = _doc_parent_folder(doc_id)
    if parent is None:
        return True, ""  # Root or unknown
    if parent in allowed:
        return True, ""
    return False, f"Doc not in allowed folder. Parent: {parent}, allowed: {allowed}"


def _gate_write(tool_name: str, doc_id: str) -> Optional[str]:
    """Returns error message if write should be blocked, else None."""
    if _read_only():
        return "Read-only mode: writes are disabled"
    if doc_id == "new":
        # Create: check target folder
        tf = _target_folder()
        if tf and not is_folder_allowed(tf):
            return f"Target folder {tf} not in allow-list"
        return None
    ok, err = _check_allow_list(doc_id)
    if not ok:
        return err
    return None


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
def gdocs_create(title: str, content: str = "") -> str:
    """Create a new doc in the target folder. content: optional markdown."""
    err = _gate_write("create", "new")
    if err:
        return json.dumps({"error": err})
    try:
        out = create_doc(title, content or None)
        if "error" not in out:
            _append_audit("create", out.get("documentId", ""), f"title={title}")
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_update(doc_id: str, content: str) -> str:
    """Append markdown content to the end of a doc."""
    err = _gate_write("update", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = update_doc(doc_id, content)
        if "error" not in out:
            _append_audit("update", doc_id, "")
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_delete(doc_id: str) -> str:
    """Trash (soft delete) a doc."""
    err = _gate_write("delete", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = delete_doc(doc_id)
        if "error" not in out:
            _append_audit("delete", doc_id, "")
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
    err = _gate_write("add_tab", doc_id)
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
        if "error" not in out:
            _append_audit("add_tab", doc_id, f"tab={tab_name}")
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
    err = _gate_write("find_replace", doc_id)
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
        if "error" not in out:
            _append_audit("find_replace", doc_id, f"find={find_text[:50]}")
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gdocs_write_to_tab(doc_id: str, tab_id: str, content: str) -> str:
    """Insert markdown content at the start of a specific tab."""
    err = _gate_write("write_to_tab", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        out = _write_to_tab(doc_id, tab_id, content)
        if "error" not in out:
            _append_audit("write_to_tab", doc_id, f"tab={tab_id}")
        return json.dumps(out, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


# --- Phase 3: safety helpers (exposed for testing) ---

def is_read_only() -> bool:
    return _read_only()


def is_folder_allowed(folder_id: str) -> bool:
    """Check if folder_id is in the allow-list. Empty allow-list = all allowed."""
    allowed = _allowed_folders()
    if not allowed:
        return True
    return folder_id in allowed


# --- Phase 4: slides, share, search, person-chip ---

@mcp.tool
def gdocs_slides_create(title: str, folder_id: str = "") -> str:
    """Create a Google Slides presentation. folder_id: optional; uses target folder if empty.
    Limitation: Requires Slides API; may fail if not enabled."""
    fid = folder_id or _target_folder()
    if not fid:
        return json.dumps({"error": "No folder_id and GDOCS_TARGET_FOLDER_ID not set"})
    try:
        resp = _api("POST", "https://slides.googleapis.com/v1/presentations", {"title": title})
        if "error" in resp:
            return json.dumps(resp)
        pres_id = resp.get("presentationId")
        # Move to folder via Drive API
        file_info = _api("GET", f"https://www.googleapis.com/drive/v3/files/{pres_id}?fields=parents")
        current = ",".join(file_info.get("parents", []))
        if current:
            _api(
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
def gdocs_share(doc_id: str, email: str, role: str = "writer") -> str:
    """Share a doc with an email. role: reader, writer, or commenter."""
    if role not in ("reader", "writer", "commenter"):
        return json.dumps({"error": f"Invalid role: {role}"})
    err = _gate_write("share", doc_id)
    if err:
        return json.dumps({"error": err})
    try:
        # Create permission via Drive API
        body = {
            "type": "user",
            "role": role,
            "emailAddress": email,
        }
        resp = _api(
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
    err = _gate_write("insert_person", doc_id)
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
        resp = _api(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            {"requests": [req]},
        )
        if "error" in resp:
            return json.dumps(resp)
        return json.dumps({
            "status": "inserted",
            "documentId": doc_id,
            "email": email,
            "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        })
    except Exception as e:
        return json.dumps({"error": str(e), "hint": "Person chips may require People API scope"})


def main() -> None:
    mcp.run()
