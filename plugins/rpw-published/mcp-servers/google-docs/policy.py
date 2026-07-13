"""
Safety/policy layer for the Google Docs MCP server.

Read-only mode, folder allow-list, audit logging, and Docs-API error mapping —
the gating that wraps every mutating tool. Network access is re-exported from
``auth`` so the whole policy + tool surface can be driven through a single
patch point (``policy.api``) in tests.
"""

import os
from datetime import datetime
from typing import Any, Optional

from auth import api
from auth import multipart_upload


def is_read_only() -> bool:
    return os.environ.get("GDOCS_READ_ONLY", "false").lower() in ("1", "true", "yes")


def allowed_folders() -> list[str]:
    raw = os.environ.get("GDOCS_ALLOWED_FOLDERS", "")
    if not raw:
        return []
    return [f.strip() for f in raw.split(",") if f.strip()]


def target_folder() -> str:
    return os.environ.get("GDOCS_TARGET_FOLDER_ID", "")


def is_folder_allowed(folder_id: str) -> bool:
    """Check if folder_id is in the allow-list. Empty allow-list = all allowed."""
    allowed = allowed_folders()
    if not allowed:
        return True
    return folder_id in allowed


def audit_log_path() -> Optional[str]:
    return os.environ.get("GDOCS_AUDIT_LOG_PATH")


def append_audit(op: str, doc_id: str, extra: str = "") -> None:
    path = audit_log_path()
    if not path:
        return
    line = f"{datetime.utcnow().isoformat()}Z\t{op}\t{doc_id}\t{extra}\n"
    try:
        with open(path, "a") as f:
            f.write(line)
    except OSError:
        pass


def doc_parent_folder(doc_id: str) -> Optional[str]:
    """Get the parent folder ID of a doc. Returns None if not in a folder."""
    try:
        resp = api("GET", f"https://www.googleapis.com/drive/v3/files/{doc_id}?fields=parents")
        parents = resp.get("parents", [])
        return parents[0] if parents else None
    except Exception:
        return None


def check_allow_list(doc_id: str) -> tuple[bool, str]:
    """Returns (allowed, error_msg)."""
    allowed = allowed_folders()
    if not allowed:
        return True, ""
    parent = doc_parent_folder(doc_id)
    if parent is None:
        return True, ""  # Root or unknown
    if parent in allowed:
        return True, ""
    return False, f"Doc not in allowed folder. Parent: {parent}, allowed: {allowed}"


def is_missing_target_error(resp: Any) -> bool:
    """True if an API error envelope indicates a missing tab/object target.

    The live Docs API returns ``400 INVALID_ARGUMENT`` with a message like
    "A tab with ID ... does not exist." for missing tab/parent references — NOT a
    404 (#160). Map both that and the defensive 404 so tab-target tools return a
    clean idempotent ``not_found`` instead of leaking the raw Google envelope (#162).
    """
    if not isinstance(resp, dict):
        return False
    err_info = resp.get("error")
    if not isinstance(err_info, dict):
        return False
    code = err_info.get("code", 0)
    message = err_info.get("message", "")
    return code == 404 or (code == 400 and "does not exist" in message)


def gate_write(tool_name: str, doc_id: str) -> Optional[str]:
    """Returns error message if write should be blocked, else None."""
    if is_read_only():
        return "Read-only mode: writes are disabled"
    if doc_id == "new":
        # Create: check target folder
        tf = target_folder()
        if tf and not is_folder_allowed(tf):
            return f"Target folder {tf} not in allow-list"
        return None
    ok, err = check_allow_list(doc_id)
    if not ok:
        return err
    return None
