"""Read-only audit for duplicate Notion Calendar "Busy" blocks in Google Calendar (#1310).

Notion Calendar's auto-blocking writes destination "Busy" events into a Google
calendar and stamps each one with the SOURCE event's identity in the destination
event's *private* extended properties. Notion exposes the blocking rule in its
UI but no API for inspecting, deduplicating, or verifying the Google events it
produced, so a duplicate storm is invisible until a human scrolls a calendar.

This module is the grouping half of the guardrail. It is deliberately pure:
stdlib only, no HTTP, no `fastmcp`, no `databricks-sdk`, and **no write or delete
path anywhere**. `mcp_server.py` owns the paginated `events.list` reads and hands
the raw `items` here; `tests/test_notion_calendar_dupe_guard.py` exercises it
directly, which is why it must stay importable without the server's deps.

Two properties are load-bearing and each has a test:

1. **Identity, never coincidence.** A group is keyed on Notion's source tuple.
   Equal title and equal time are NOT duplicate evidence — a calendar legitimately
   holds two 9am "Busy" blocks from two different source events, and collapsing
   those would send a future cleanup after a real block.
2. **Recurrence identity survives.** With `singleEvents=true` one destination
   recurring event expands into many instances that all share the same source
   tuple. Grouping on the tuple alone would report a 40-way "duplicate" for a
   perfectly healthy weekly block, so the group key carries the instance slot
   (`originalStartTime`) alongside the tuple. Distinct series that collide on the
   same slot are the real duplicates, and the group records their
   `recurringEventId`s so a human can tell the shapes apart.

Field names match the Google Calendar v3 Event resource exactly
(https://developers.google.com/workspace/calendar/api/v3/reference/events):
`status`, `recurringEventId`, `originalStartTime`, `extendedProperties.private`,
`organizer.self`, `attendees`, `conferenceData`, `transparency`, `eventType`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

# Notion Calendar (formerly Cron) stamps the source identity under these three
# PRIVATE extended-property keys. Private, not shared: they come back from
# `events.list` only for the account that wrote them, which is also why a local
# cache is not a substitute for asking the Calendar API.
SOURCE_ACCOUNT_KEY = "cron.syncOriginalAccountId"
SOURCE_CALENDAR_KEY = "cron.syncOriginalCalendarId"
SOURCE_EVENT_KEY = "cron.syncOriginalEventId"
SOURCE_TUPLE_KEYS = (SOURCE_ACCOUNT_KEY, SOURCE_CALENDAR_KEY, SOURCE_EVENT_KEY)

# Notion writes this exact title. Used only as ONE predicate in the cleanup
# screen — never as duplicate evidence on its own.
BUSY_SUMMARY = "Busy"

CANCELLED = "cancelled"
CONFIRMED = "confirmed"


# --- source identity -------------------------------------------------------


def private_properties(event: dict[str, Any]) -> dict[str, str]:
    """Return `extendedProperties.private` as a str->str dict, or {}.

    Tolerant by design: absent, null, or non-dict shapes all read as "no private
    properties" rather than raising, because one malformed event must not abort
    an audit over hundreds.
    """
    extended = event.get("extendedProperties")
    if not isinstance(extended, dict):
        return {}
    private = extended.get("private")
    if not isinstance(private, dict):
        return {}
    return {str(k): str(v) for k, v in private.items()}


def source_tuple(event: dict[str, Any]) -> tuple[str, str, str] | None:
    """Return (accountId, calendarId, eventId) from private props, else None.

    None means "not a Notion-managed destination block" — every key must be
    present and non-empty. A partial stamp is treated as unmanaged, not as a
    duplicate candidate: acting on a half-identified event is exactly the
    mistake the no-delete default exists to prevent.
    """
    private = private_properties(event)
    values = [private.get(key, "").strip() for key in SOURCE_TUPLE_KEYS]
    if not all(values):
        return None
    return (values[0], values[1], values[2])


def source_tuple_dict(tuple_: tuple[str, str, str]) -> dict[str, str]:
    """Render a source tuple with its literal Google/Notion property keys."""
    return dict(zip(SOURCE_TUPLE_KEYS, tuple_))


# --- time helpers ----------------------------------------------------------


def _timestamp(node: Any) -> str | None:
    """Return the RFC3339 `dateTime`, else the all-day `date`, from a time node."""
    if not isinstance(node, dict):
        return None
    for key in ("dateTime", "date"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_rfc3339(value: str | None) -> datetime | None:
    """Parse an RFC3339 timestamp or all-day date into an aware datetime, else None.

    A trailing `Z` is rewritten to `+00:00` because `datetime.fromisoformat` only
    learned to accept `Z` in 3.11 and this server supports 3.10. A bare `date`
    (all-day event) becomes UTC midnight, and a naive timestamp is assumed UTC —
    both are stated assumptions, and the cleanup screen fails CLOSED when a value
    will not parse at all.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def instance_slot(event: dict[str, Any]) -> str | None:
    """Return the recurrence instance discriminator: `originalStartTime`, else None.

    This is what keeps a healthy weekly destination block from reading as a
    40-way duplicate. None means "not a recurring instance" (a one-off event).
    """
    return _timestamp(event.get("originalStartTime"))


# --- candidate rows --------------------------------------------------------


def candidate_row(event: dict[str, Any], *, calendar_id: str) -> dict[str, Any]:
    """Flatten one destination event into an audit/export row.

    Keeps recurrence identity (`recurringEventId`, `originalStartTime`) and the
    predicate inputs a future gated cleanup would have to re-check, so the export
    is self-sufficient evidence rather than a pointer back into the calendar.
    """
    attendees = event.get("attendees")
    return {
        "calendarId": calendar_id,
        "eventId": event.get("id"),
        "iCalUID": event.get("iCalUID"),
        "status": event.get("status"),
        "summary": event.get("summary"),
        "start": _timestamp(event.get("start")),
        "end": _timestamp(event.get("end")),
        "recurringEventId": event.get("recurringEventId"),
        "originalStartTime": instance_slot(event),
        "organizerSelf": bool((event.get("organizer") or {}).get("self")) if isinstance(event.get("organizer"), dict) else False,
        "attendeeCount": len(attendees) if isinstance(attendees, list) else 0,
        "hasConferenceData": isinstance(event.get("conferenceData"), dict),
        "transparency": event.get("transparency"),
        "eventType": event.get("eventType"),
        "created": event.get("created"),
        "updated": event.get("updated"),
        "htmlLink": event.get("htmlLink"),
        "sourceTuple": source_tuple_dict(source_tuple(event)) if source_tuple(event) else None,
    }


# --- the audit -------------------------------------------------------------


def group_duplicates(
    events: Iterable[dict[str, Any]],
    *,
    calendar_id: str = "primary",
    time_min: str = "",
    time_max: str = "",
    min_group_size: int = 2,
) -> dict[str, Any]:
    """Group destination events by source tuple + instance slot; report duplicates.

    Read-only and total: every input event lands in exactly one bucket —
    a duplicate group, a singleton, or one of the two exclusion counters
    (`cancelled`, `unmanaged`). The counts therefore reconcile against
    `eventsScanned`, which is what makes "no duplicates found" trustworthy
    instead of merely quiet.

    `min_group_size` is the duplicate threshold and defaults to 2. Values below
    2 are clamped up: a "group" of one is a normal block, and reporting it as a
    duplicate would hand a future cleanup a target on every healthy event.
    """
    threshold = max(int(min_group_size), 2)
    groups: dict[tuple[str, str, str, str | None], list[dict[str, Any]]] = {}
    scanned = 0
    excluded_cancelled = 0
    excluded_unmanaged = 0

    for event in events:
        if not isinstance(event, dict):
            continue
        scanned += 1
        if (event.get("status") or "").strip().lower() == CANCELLED:
            excluded_cancelled += 1
            continue
        tuple_ = source_tuple(event)
        if tuple_ is None:
            excluded_unmanaged += 1
            continue
        key = (tuple_[0], tuple_[1], tuple_[2], instance_slot(event))
        groups.setdefault(key, []).append(candidate_row(event, calendar_id=calendar_id))

    duplicate_groups = []
    singletons = 0
    for key, rows in groups.items():
        # Distinct destination event ids only. An `events.list` page can repeat
        # an id across pages when the window straddles a sync, and counting the
        # repeat would inflate a healthy block into a duplicate.
        unique: dict[str, dict[str, Any]] = {}
        for row in rows:
            unique.setdefault(str(row["eventId"]), row)
        members = sorted(unique.values(), key=lambda r: (r.get("start") or "", str(r.get("eventId") or "")))
        if len(members) < threshold:
            singletons += 1
            continue
        starts = [r["start"] for r in members if r["start"]]
        ends = [r["end"] for r in members if r["end"]]
        duplicate_groups.append(
            {
                "sourceTuple": source_tuple_dict((key[0], key[1], key[2])),
                "instanceSlot": key[3],
                "duplicateCount": len(members),
                "destinationEventIds": [r["eventId"] for r in members],
                "recurringEventIds": sorted({r["recurringEventId"] for r in members if r["recurringEventId"]}),
                "summaries": sorted({r["summary"] for r in members if r["summary"]}),
                "timeRange": {
                    "earliestStart": min(starts) if starts else None,
                    "latestEnd": max(ends) if ends else None,
                },
                "candidates": members,
            }
        )

    duplicate_groups.sort(
        key=lambda g: (-g["duplicateCount"], str(g["sourceTuple"][SOURCE_EVENT_KEY]), str(g["instanceSlot"] or ""))
    )

    return {
        "ok": True,
        "readOnly": True,
        "noDeleteDefault": True,
        "calendarId": calendar_id,
        "window": {"timeMin": time_min or None, "timeMax": time_max or None},
        "groupedBy": list(SOURCE_TUPLE_KEYS) + ["originalStartTime"],
        "minGroupSize": threshold,
        "summary": {
            "eventsScanned": scanned,
            "excludedCancelled": excluded_cancelled,
            "excludedUnmanaged": excluded_unmanaged,
            "notionManagedGroups": len(groups),
            "singletonGroups": singletons,
            "duplicateGroups": len(duplicate_groups),
            "duplicateEvents": sum(g["duplicateCount"] for g in duplicate_groups),
        },
        "duplicateGroups": duplicate_groups,
    }


# --- cleanup screen (no delete path) ---------------------------------------

CLEANUP_PREDICATES = (
    "source_tuple_exact",
    "status_confirmed",
    "within_time_range",
    "summary_is_busy",
    "organizer_self",
    "no_attendees",
    "no_conference",
    "not_retained",
)

_DELETE_DISABLED_REASON = (
    "No delete path exists in this module or its MCP server (#1310). This screen "
    "exports candidates and evaluates every predicate so a human can review them; "
    "deleting is a separate, explicitly-gated capability that has not been built."
)


def screen_cleanup_candidates(
    events: Iterable[dict[str, Any]],
    *,
    source_account_id: str,
    source_calendar_id: str,
    source_event_id: str,
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
    expected_summary: str = BUSY_SUMMARY,
) -> dict[str, Any]:
    """Evaluate cleanup predicates against ONE exact source tuple. Never deletes.

    Refuses outright unless all three source-tuple components are supplied: the
    issue's hard requirement is that any future cleanup name an exact tuple, and
    a screen that answers a partial tuple is a screen that would eventually be
    handed one.

    Every predicate is reported per candidate rather than collapsed to a boolean,
    and every unparseable timestamp fails CLOSED (`within_time_range` false), so
    a row is "eligible" only when the evidence positively says so. Exactly one
    member of the surviving set is marked `retained` — the earliest-created
    confirmed row — so no screen output can ever describe removing an entire
    group.
    """
    requested = (
        (source_account_id or "").strip(),
        (source_calendar_id or "").strip(),
        (source_event_id or "").strip(),
    )
    if not all(requested):
        return {
            "ok": False,
            "error": "source_tuple_required",
            "detail": (
                "All three components are required: "
                f"{SOURCE_ACCOUNT_KEY}, {SOURCE_CALENDAR_KEY}, {SOURCE_EVENT_KEY}. "
                "Run the audit first and copy an exact tuple from a duplicate group."
            ),
            "deleteEnabled": False,
            "deleteImplemented": False,
        }
    if not (time_min or "").strip() or not (time_max or "").strip():
        return {
            "ok": False,
            "error": "time_range_required",
            "detail": "Both time_min and time_max (RFC3339) are required to bound the screen.",
            "deleteEnabled": False,
            "deleteImplemented": False,
        }

    window_start = parse_rfc3339(time_min)
    window_end = parse_rfc3339(time_max)
    if window_start is None or window_end is None:
        return {
            "ok": False,
            "error": "time_range_unparseable",
            "detail": "time_min and time_max must be RFC3339 timestamps (e.g. 2026-09-16T00:00:00Z).",
            "deleteEnabled": False,
            "deleteImplemented": False,
        }

    matched = [
        event
        for event in events
        if isinstance(event, dict) and source_tuple(event) == requested
    ]
    rows = [candidate_row(event, calendar_id=calendar_id) for event in matched]
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(str(row["eventId"]), row)
    rows = sorted(unique.values(), key=lambda r: (r.get("created") or "", str(r.get("eventId") or "")))

    # The keeper: earliest-created confirmed row. Chosen before predicates so
    # that a group whose members ALL pass still keeps one.
    retained_id = next(
        (r["eventId"] for r in rows if (r.get("status") or "").lower() == CONFIRMED),
        rows[0]["eventId"] if rows else None,
    )

    screened = []
    for row in rows:
        start = parse_rfc3339(row.get("start"))
        end = parse_rfc3339(row.get("end"))
        in_range = bool(
            start is not None
            and end is not None
            and start >= window_start
            and end <= window_end
        )
        checks = {
            "source_tuple_exact": True,  # `matched` already enforced it
            "status_confirmed": (row.get("status") or "").lower() == CONFIRMED,
            "within_time_range": in_range,
            "summary_is_busy": (row.get("summary") or "").strip().casefold()
            == expected_summary.strip().casefold(),
            "organizer_self": bool(row.get("organizerSelf")),
            "no_attendees": row.get("attendeeCount", 0) == 0,
            "no_conference": not row.get("hasConferenceData"),
            "not_retained": row["eventId"] != retained_id,
        }
        screened.append(
            {
                **row,
                "retained": row["eventId"] == retained_id,
                "checks": checks,
                "failedChecks": sorted(name for name, passed in checks.items() if not passed),
                "eligible": all(checks.values()),
            }
        )

    return {
        "ok": True,
        "readOnly": True,
        "deleteEnabled": False,
        "deleteImplemented": False,
        "deleteDisabledReason": _DELETE_DISABLED_REASON,
        "exportFirst": True,
        "calendarId": calendar_id,
        "sourceTuple": source_tuple_dict(requested),
        "window": {"timeMin": time_min, "timeMax": time_max},
        "predicates": list(CLEANUP_PREDICATES),
        "retainedEventId": retained_id,
        "summary": {
            "matched": len(rows),
            "eligible": sum(1 for r in screened if r["eligible"]),
            "retained": 1 if retained_id else 0,
        },
        "candidates": screened,
    }


# --- events.list parameter shaping -----------------------------------------

# Ceiling on pages the audit will pull, so a careless multi-year window cannot
# loop indefinitely against the API. 20 pages x 250 events = 5000 events.
MAX_AUDIT_PAGES = 20
MAX_PAGE_SIZE = 2500


def build_events_list_params(
    *,
    time_min: str = "",
    time_max: str = "",
    page_size: int = 250,
    page_token: str = "",
    single_events: bool = True,
    show_deleted: bool = False,
    private_extended_property: str = "",
    query: str = "",
) -> dict[str, str]:
    """Shape `events.list` query params for the audit read path.

    `private_extended_property` is a single `propertyName=value` constraint. The
    Calendar API accepts the parameter repeated (AND-ing the constraints), but the
    UC http_request transport carries `params` as a string->string MAP, which
    cannot express a repeated key — so exactly ONE constraint is reachable here
    and the full three-key tuple match is enforced locally by `source_tuple`.
    One constraint (`cron.syncOriginalEventId=...`) already narrows to a single
    source event; the local match is what makes it exact.

    `show_deleted` stays False so cancelled events never enter the audit — the
    issue requires excluding them, and excluding them at the API is cheaper and
    less error-prone than filtering a page you already paid to transfer.
    `group_duplicates` re-checks `status` anyway, because the two `singleEvents`
    modes differ in what they return.
    """
    params: dict[str, str] = {
        "maxResults": str(min(max(int(page_size), 1), MAX_PAGE_SIZE)),
        "singleEvents": "true" if single_events else "false",
        "showDeleted": "true" if show_deleted else "false",
        # `startTime` ordering is only legal with singleEvents=true.
        "orderBy": "startTime" if single_events else "updated",
    }
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    if page_token:
        params["pageToken"] = page_token
    if query:
        params["q"] = query
    constraint = (private_extended_property or "").strip()
    if constraint:
        if "=" not in constraint:
            raise ValueError(
                "private_extended_property must be 'propertyName=value', "
                f"e.g. '{SOURCE_EVENT_KEY}=abc123'"
            )
        params["privateExtendedProperty"] = constraint
    return params


def strip_candidates(report: dict[str, Any]) -> dict[str, Any]:
    """Return the report with per-group `candidates` lists removed.

    A wide window over a duplicate storm produces a report far larger than an
    agent's context can carry. The group header — source tuple, ids, recurrence
    ids, count, time range — is what a human triages on; the full rows are for
    the export.
    """
    trimmed = dict(report)
    trimmed["duplicateGroups"] = [
        {k: v for k, v in group.items() if k != "candidates"}
        for group in report.get("duplicateGroups", [])
    ]
    trimmed["candidatesOmitted"] = True
    return trimmed
