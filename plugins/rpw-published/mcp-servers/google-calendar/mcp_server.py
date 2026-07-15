#!/usr/bin/env python3
"""Google Calendar MCP server — FastMCP over a Databricks UC HTTP-proxy connection.

Exposes the Calendar v3 API surface only. Drive (including the `about` identity
endpoint), Gmail, Tasks, and Docs each have dedicated sibling servers.
"""

import sys
from pathlib import Path
from typing import Any

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod
from fastmcp import FastMCP

from lib import uc_proxy_client

mcp = FastMCP(name="google-calendar-uc-mcp")


# --- Calendar ---


@mcp.tool
def google_calendar_list_calendars() -> str:
    """List all calendars on the user's calendar list."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        "calendar/v3/users/me/calendarList",
    )


@mcp.tool
def google_calendar_list_events(
    calendar_id: str = "primary",
    time_min: str = "",
    time_max: str = "",
    query: str = "",
    max_results: int = 25,
    single_events: bool = True,
) -> str:
    """List events on a calendar.

    time_min / time_max: RFC3339 timestamps (e.g. '2026-04-29T00:00:00Z'). Empty = no bound.
    query: free-text search across event fields. single_events expands recurring instances.
    max_results clamped to 1..250.
    """
    params: dict[str, str] = {
        "maxResults": str(min(max(max_results, 1), 250)),
        "singleEvents": "true" if single_events else "false",
        "orderBy": "startTime" if single_events else "updated",
    }
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    if query:
        params["q"] = query
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        f"calendar/v3/calendars/{calendar_id}/events",
        query_params=params,
    )


@mcp.tool
def google_calendar_get_event(event_id: str, calendar_id: str = "primary") -> str:
    """Get a calendar event by ID."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        f"calendar/v3/calendars/{calendar_id}/events/{event_id}",
    )


@mcp.tool
def google_calendar_create_event(
    summary: str,
    start_iso: str,
    end_iso: str,
    calendar_id: str = "primary",
    description: str = "",
    location: str = "",
    attendees: str = "",
) -> str:
    """Create a calendar event.

    start_iso / end_iso: RFC3339 with timezone (e.g. '2026-04-29T15:00:00-05:00'). Use date-only strings for all-day events.
    attendees: comma-separated emails.
    """
    body: dict[str, Any] = {
        "summary": summary,
        "start": ({"date": start_iso} if "T" not in start_iso else {"dateTime": start_iso}),
        "end": ({"date": end_iso} if "T" not in end_iso else {"dateTime": end_iso}),
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [
            {"email": a.strip()} for a in attendees.split(",") if a.strip()
        ]
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.POST,
        f"calendar/v3/calendars/{calendar_id}/events",
        json_body=body,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
