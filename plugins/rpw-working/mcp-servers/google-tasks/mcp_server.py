#!/usr/bin/env python3
"""
Google Tasks MCP Server.

Exposes tools for task lists and tasks CRUD. Ensures showAssigned=true on tasks
listing so assigned tasks (from Docs, Chat Spaces) are visible.
"""

import json
import os
from typing import Any, Optional

from fastmcp import FastMCP
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

mcp = FastMCP(name="google-tasks")

# --- Credentials ---

REQUIRED_VARS = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"]


def _build_credentials() -> Credentials:
    return Credentials(
        token=None,
        refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )


def _get_service():
    """Build and return Tasks API service. Validates env on first use."""
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        raise RuntimeError(f"Missing env vars: {missing}")
    creds = _build_credentials()
    return build("tasks", "v1", credentials=creds)


# --- Tools ---


@mcp.tool
def gtasks_list_tasklists() -> str:
    """List all Google Tasks task lists. Returns JSON with id, title for each list."""
    try:
        service = _get_service()
        result = service.tasklists().list().execute()
        items = result.get("items", [])
        out = [{"id": tl["id"], "title": tl.get("title", "")} for tl in items]
        return json.dumps({"tasklists": out}, ensure_ascii=False)
    except HttpError as e:
        return json.dumps({"error": f"HTTP {e.resp.status}: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gtasks_list_tasks(
    tasklist_id: str = "@default",
    show_completed: bool = True,
    max_results: int = 100,
) -> str:
    """List tasks in a task list. Uses showAssigned=true so assigned tasks (from Docs, Chat) are included.
    tasklist_id: task list ID or '@default' for default list.
    show_completed: include completed tasks.
    max_results: max tasks to return (default 100)."""
    try:
        service = _get_service()
        result = (
            service.tasks()
            .list(
                tasklist=tasklist_id,
                showAssigned=True,  # CRITICAL: include assigned tasks from Docs/Chat Spaces
                showCompleted=show_completed,
                maxResults=min(max_results, 100),
            )
            .execute()
        )
        items = result.get("items", [])
        out = []
        for t in items:
            out.append(
                {
                    "id": t.get("id"),
                    "title": t.get("title", ""),
                    "status": t.get("status", "needsAction"),
                    "due": t.get("due"),
                    "notes": t.get("notes"),
                    "parent": t.get("parent"),
                }
            )
        return json.dumps({"tasks": out, "tasklist_id": tasklist_id}, ensure_ascii=False)
    except HttpError as e:
        return json.dumps({"error": f"HTTP {e.resp.status}: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gtasks_create_task(
    title: str,
    tasklist_id: str = "@default",
    notes: str = "",
    due: str = "",
    parent_task_id: str = "",
) -> str:
    """Create a task. due: RFC 3339 date (e.g. 2025-01-15T00:00:00.000Z). parent_task_id: for subtasks."""
    try:
        service = _get_service()
        body: dict[str, Any] = {"title": title}
        if notes:
            body["notes"] = notes
        if due:
            body["due"] = due
        params: dict[str, Any] = {"tasklist": tasklist_id, "body": body}
        if parent_task_id:
            params["parent"] = parent_task_id
        result = service.tasks().insert(**params).execute()
        return json.dumps(
            {
                "status": "created",
                "id": result.get("id"),
                "title": result.get("title"),
                "tasklist_id": tasklist_id,
            },
            ensure_ascii=False,
        )
    except HttpError as e:
        return json.dumps({"error": f"HTTP {e.resp.status}: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gtasks_update_task(
    tasklist_id: str,
    task_id: str,
    title: Optional[str] = None,
    notes: Optional[str] = None,
    due: Optional[str] = None,
) -> str:
    """Update a task. Pass only fields to change."""
    try:
        service = _get_service()
        body: dict[str, Any] = {}
        if title is not None:
            body["title"] = title
        if notes is not None:
            body["notes"] = notes
        if due is not None:
            body["due"] = due
        if not body:
            return json.dumps({"error": "No fields to update"})
        result = service.tasks().patch(
            tasklist=tasklist_id, task=task_id, body=body
        ).execute()
        return json.dumps(
            {
                "status": "updated",
                "id": result.get("id"),
                "title": result.get("title"),
            },
            ensure_ascii=False,
        )
    except HttpError as e:
        return json.dumps({"error": f"HTTP {e.resp.status}: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gtasks_complete_task(tasklist_id: str, task_id: str) -> str:
    """Mark a task as completed."""
    try:
        service = _get_service()
        result = service.tasks().patch(
            tasklist=tasklist_id, task=task_id, body={"status": "completed"}
        ).execute()
        return json.dumps(
            {"status": "completed", "id": result.get("id"), "title": result.get("title")},
            ensure_ascii=False,
        )
    except HttpError as e:
        return json.dumps({"error": f"HTTP {e.resp.status}: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool
def gtasks_delete_task(tasklist_id: str, task_id: str) -> str:
    """Delete a task."""
    try:
        service = _get_service()
        service.tasks().delete(tasklist=tasklist_id, task=task_id).execute()
        return json.dumps(
            {"status": "deleted", "id": task_id, "tasklist_id": tasklist_id},
            ensure_ascii=False,
        )
    except HttpError as e:
        return json.dumps({"error": f"HTTP {e.resp.status}: {e.reason}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


def main() -> None:
    mcp.run()
