"""
Tests for Google Tasks MCP server.
- Unit test: asserts tasks list request uses showAssigned=True (mocked).
- Connectivity test: validates credentials and API reach (optional, requires .env).
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

REQUIRED_VARS = ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"]


# --- Unit test: showAssigned=True ---

def test_list_tasks_uses_show_assigned_true():
    """Assert that gtasks_list_tasks passes showAssigned=True to the Tasks API."""
    import mcp_server

    mock_list = MagicMock()
    mock_list.return_value.execute.return_value = {"items": []}
    mock_tasks = MagicMock()
    mock_tasks.list = mock_list
    mock_service = MagicMock()
    mock_service.tasks.return_value = mock_tasks

    with patch.object(mcp_server, "_get_service", return_value=mock_service):
        result = mcp_server.gtasks_list_tasks("@default")

    mock_list.assert_called_once()
    call_kwargs = mock_list.call_args[1]
    assert call_kwargs.get("showAssigned") is True, (
        f"Expected showAssigned=True in tasks.list() call, got {call_kwargs}"
    )
    # Verify result is valid JSON
    data = json.loads(result)
    assert "tasks" in data
    assert data["tasklist_id"] == "@default"


# --- Connectivity test (requires .env) ---

def check_env() -> bool:
    missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
    if missing:
        print(f"⚠️  Skipping connectivity test: missing env vars {missing}")
        return False
    return True


def build_credentials() -> Credentials:
    return Credentials(
        token=None,
        refresh_token=os.getenv("GOOGLE_REFRESH_TOKEN"),
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )


def test_connectivity():
    """Validate credentials and API reach. Skips if .env vars missing."""
    if not check_env():
        return

    print("\n--- Connectivity: Building credentials ---")
    creds = build_credentials()

    print("--- Building Tasks API client ---")
    try:
        service = build("tasks", "v1", credentials=creds)
        print("✅ API client built")
    except Exception as e:
        raise AssertionError(f"Failed to build API client: {e}") from e

    print("--- List task lists ---")
    result = service.tasklists().list().execute()
    items = result.get("items", [])
    if not items:
        print("⚠️  No task lists found (API call succeeded)")
        return
    print(f"✅ Found {len(items)} task list(s)")

    print("--- List tasks with showAssigned=True ---")
    first = items[0]
    result = (
        service.tasks()
        .list(
            tasklist=first["id"],
            showAssigned=True,
            maxResults=5,
        )
        .execute()
    )
    tasks = result.get("items", [])
    print(f"✅ Listed {len(tasks)} task(s) from '{first['title']}'")


def run_tests():
    """Run unit test and optionally connectivity test."""
    print("=== Google Tasks MCP Tests ===\n")

    # Unit test (always runs)
    print("--- Unit test: showAssigned=True ---")
    test_list_tasks_uses_show_assigned_true()
    print("✅ showAssigned=True assertion passed\n")

    # Connectivity test (if .env present)
    print("--- Connectivity test ---")
    try:
        test_connectivity()
    except HttpError as e:
        print(f"❌ HTTP error: {e.resp.status} — {e.reason}")
        print("   Hint: check that your refresh token has the Tasks API scope.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)

    print("\n✅ All tests passed")


if __name__ == "__main__":
    run_tests()
