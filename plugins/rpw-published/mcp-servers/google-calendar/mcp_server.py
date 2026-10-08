#!/usr/bin/env python3
"""Google Calendar MCP server — FastMCP over a Databricks UC HTTP-proxy connection.

Exposes the Calendar v3 API surface only. Drive (including the `about` identity
endpoint), Gmail, Tasks, and Docs each have dedicated sibling servers.
"""

import json
import sys
from pathlib import Path
from typing import Any

# Allow imports from the parent mcp-servers directory (shared lib/) and from this
# server's own directory (notion_dupe), so the module resolves however the
# launcher was invoked rather than only when cwd happens to be the server dir.
_SERVER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SERVER_DIR.parent))
sys.path.insert(0, str(_SERVER_DIR))

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod
from fastmcp import FastMCP

import notion_dupe
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
    page_token: str = "",
    show_deleted: bool = False,
    private_extended_property: str = "",
) -> str:
    """List events on a calendar (one page).

    time_min / time_max: RFC3339 timestamps (e.g. '2026-04-29T00:00:00Z'). Empty = no bound.
    query: free-text search across event fields. single_events expands recurring instances.
    max_results clamped to 1..2500 (the API's page ceiling).

    page_token: pass the previous response's `nextPageToken` to read the next page.
      Without it a window wider than one page silently truncates.
    show_deleted: include cancelled events. Default False.
    private_extended_property: ONE `propertyName=value` constraint on the event's
      private extended properties, e.g. 'cron.syncOriginalEventId=abc123'. The
      Calendar API allows repeats; the UC transport carries params as a map, so
      only one constraint is reachable here.

    Responses are raw Event resources, so `extendedProperties`, `recurringEventId`
    and `originalStartTime` come through untouched — that is what the Notion
    duplicate audit groups on.
    """
    params = notion_dupe.build_events_list_params(
        time_min=time_min,
        time_max=time_max,
        page_size=max_results,
        page_token=page_token,
        single_events=single_events,
        show_deleted=show_deleted,
        private_extended_property=private_extended_property,
        query=query,
    )
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


# --- Notion Calendar duplicate-block guardrail (#1310) ---
#
# READ-ONLY BY CONSTRUCTION. Both tools below issue GET only. There is no delete
# tool in this server and none is planned here: the issue's hard requirement is
# that cleanup be a separately gated capability, so the guardrail ships the
# audit and the screen, and stops there.


def _audit_pages(
    *,
    calendar_id: str,
    time_min: str,
    time_max: str,
    page_size: int,
    max_pages: int,
    private_extended_property: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, int, bool]:
    """Pull up to `max_pages` of `events.list`; return (items, error, pages, truncated).

    Pagination is the gap that made the audit impossible before: one page caps at
    2500 events and the previous tool had no `pageToken`, so a duplicate storm
    past the first page was invisible. The page budget is bounded so a careless
    multi-year window fails loudly (`truncated: true`) instead of looping.
    """
    items: list[dict[str, Any]] = []
    page_token = ""
    pages = 0
    while pages < max_pages:
        params = notion_dupe.build_events_list_params(
            time_min=time_min,
            time_max=time_max,
            page_size=page_size,
            page_token=page_token,
            single_events=True,
            show_deleted=False,
            private_extended_property=private_extended_property,
        )
        raw = uc_proxy_client.request_via_env(
            ExternalFunctionRequestHttpMethod.GET,
            f"calendar/v3/calendars/{calendar_id}/events",
            query_params=params,
        )
        pages += 1
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return items, {"ok": False, "error": "invalid_json", "raw": raw[:2000]}, pages, False
        if not isinstance(payload, dict) or payload.get("ok") is False:
            return items, payload if isinstance(payload, dict) else {"ok": False, "error": "unexpected_payload"}, pages, False
        page_items = payload.get("items")
        if isinstance(page_items, list):
            items.extend(i for i in page_items if isinstance(i, dict))
        page_token = (payload.get("nextPageToken") or "").strip()
        if not page_token:
            return items, None, pages, False
    return items, None, pages, True


@mcp.tool
def google_calendar_audit_notion_duplicate_blocks(
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
    source_event_id: str = "",
    min_group_size: int = 2,
    page_size: int = 250,
    max_pages: int = notion_dupe.MAX_AUDIT_PAGES,
    include_candidates: bool = True,
) -> str:
    """READ-ONLY audit: group duplicate Notion Calendar "Busy" blocks by source tuple.

    Notion Calendar can write several destination "Busy" events for one source
    event and offers no API to inspect them. This paginates `events.list` over
    [time_min, time_max] and groups destination events by Notion's PRIVATE source
    tuple (`cron.syncOriginalAccountId`, `cron.syncOriginalCalendarId`,
    `cron.syncOriginalEventId`) plus the recurrence instance slot
    (`originalStartTime`), so a healthy weekly block is not reported as a
    40-way duplicate. Cancelled events are excluded.

    Equal title and equal time are NOT duplicate evidence — only a shared source
    tuple is. Nothing is written or deleted.

    time_min / time_max: RFC3339, required (e.g. '2026-09-01T00:00:00Z').
    source_event_id: optional narrowing — filters server-side on
      `cron.syncOriginalEventId=<id>` before grouping.
    min_group_size: duplicate threshold, clamped to >= 2.
    include_candidates: False drops the per-event rows and keeps group headers.
    """
    if not time_min.strip() or not time_max.strip():
        return json.dumps(
            {
                "ok": False,
                "error": "time_range_required",
                "detail": "time_min and time_max (RFC3339) are required to bound the audit.",
            }
        )
    constraint = (
        f"{notion_dupe.SOURCE_EVENT_KEY}={source_event_id.strip()}"
        if source_event_id.strip()
        else ""
    )
    items, error, pages, truncated = _audit_pages(
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
        page_size=page_size,
        max_pages=min(max(int(max_pages), 1), notion_dupe.MAX_AUDIT_PAGES),
        private_extended_property=constraint,
    )
    if error is not None:
        return json.dumps({**error, "pagesFetched": pages, "stage": "events.list"})
    report = notion_dupe.group_duplicates(
        items,
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
        min_group_size=min_group_size,
    )
    report["pagesFetched"] = pages
    report["truncated"] = truncated
    if truncated:
        report["truncatedDetail"] = (
            f"Stopped at the {pages}-page budget; results are incomplete. "
            "Narrow the window or raise max_pages."
        )
    if source_event_id.strip():
        report["serverSideFilter"] = constraint
    if not include_candidates:
        report = notion_dupe.strip_candidates(report)
    return json.dumps(report, ensure_ascii=False)


@mcp.tool
def google_calendar_screen_notion_cleanup_candidates(
    source_account_id: str,
    source_calendar_id: str,
    source_event_id: str,
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
) -> str:
    """READ-ONLY screen for one EXACT source tuple. Exports candidates; never deletes.

    The gate a future cleanup would have to pass, run on its own so a human can
    review it first. Requires all three source-tuple components — a partial tuple
    is refused, not guessed. Evaluates every predicate per candidate
    (exact source tuple, confirmed status, inside the time range, `Busy` summary,
    self organizer, no attendees, no conference data) and marks exactly one
    member `retained`, so the output can never describe removing a whole group.

    Always returns `deleteEnabled: false` and `deleteImplemented: false`: this
    server has no delete path.

    Copy the tuple from a duplicate group reported by
    `google_calendar_audit_notion_duplicate_blocks`.
    """
    items, error, pages, truncated = _audit_pages(
        calendar_id=calendar_id,
        time_min=time_min,
        time_max=time_max,
        page_size=250,
        max_pages=notion_dupe.MAX_AUDIT_PAGES,
        private_extended_property=(
            f"{notion_dupe.SOURCE_EVENT_KEY}={source_event_id.strip()}"
            if source_event_id.strip()
            else ""
        ),
    )
    if error is not None:
        return json.dumps(
            {**error, "pagesFetched": pages, "stage": "events.list", "deleteEnabled": False}
        )
    screen = notion_dupe.screen_cleanup_candidates(
        items,
        source_account_id=source_account_id,
        source_calendar_id=source_calendar_id,
        source_event_id=source_event_id,
        time_min=time_min,
        time_max=time_max,
        calendar_id=calendar_id,
    )
    screen["pagesFetched"] = pages
    screen["truncated"] = truncated
    return json.dumps(screen, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
