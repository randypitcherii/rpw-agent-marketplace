# Google Calendar MCP Server

FastMCP server for the Google Calendar v3 API, proxied through a Databricks Unity Catalog HTTP-proxy connection (`http_request` external function). No raw OAuth tokens live on disk — credentials are resolved at runtime via the UC proxy.

This server owns the Calendar surface only. Drive (including the `about` identity endpoint), Gmail, Tasks, and Docs each have their own dedicated server.

## Setup

1. **Change to this server directory and create env files from `template.env`**:

   ```bash
   cd mcp-servers/google-calendar
   cp template.env dev.env
   cp template.env test.env
   cp template.env prod.env
   ```

   Required variables (populated by the `/mcp-setup` skill, or set manually):
   - `UC_PROXY_CONNECTION_NAME` (your Google UC HTTP-proxy connection name)
   - `UC_PROXY_PROFILE` (Databricks CLI profile name)

2. **Install dependencies** (uv, Python 3.10+):

   ```bash
   uv sync
   ```

## Run

From this directory (defaults to `APP_ENV=dev`):

```bash
uv run python run_mcp.py
```

To run another environment:

```bash
APP_ENV=test uv run python run_mcp.py
APP_ENV=prod uv run python run_mcp.py
```

The server runs over stdio. Register in your MCP client using `google_calendar.mcp.json` — merge the `mcpServers` block.

## Test

```bash
uv run python -m unittest test_run_mcp_env -v
```

## Tools

| Tool | Description |
| ---- | ----------- |
| `google_calendar_list_calendars` | List all calendars on the user's calendar list |
| `google_calendar_list_events` | List one page of events (time/query filters, `page_token`, `show_deleted`, one `private_extended_property` constraint) |
| `google_calendar_get_event` | Get a calendar event by ID |
| `google_calendar_create_event` | Create a calendar event (supports attendees, all-day) |
| `google_calendar_audit_notion_duplicate_blocks` | **Read-only.** Paginate a window and group duplicate Notion Calendar "Busy" blocks by source tuple + recurrence slot |
| `google_calendar_screen_notion_cleanup_candidates` | **Read-only.** Evaluate cleanup predicates for one exact source tuple; always returns `deleteEnabled: false` |

## Notion Calendar duplicate-block guardrail (#1310)

Notion Calendar auto-blocking can write several destination "Busy" events for one
source event, and Notion offers no API to inspect or deduplicate them. The two audit
tools above close that gap. Guidance, output reference, and the reset runbook live in
the `notion-calendar-dupe-guard` skill (`plugins/rpw-published/skills/notion-calendar-dupe-guard/`);
the grouping logic is `notion_dupe.py`, kept dependency-free so the repo's root pytest
gate can import it (`tests/test_notion_calendar_dupe_guard.py`).

🚫 **No delete path.** This server issues GET for every read and POST only for
`google_calendar_create_event`. There is no `events.delete` call and no delete tool;
`TestNoDeletePath` fails the gate if one appears. Any cleanup capability is a separate,
explicitly-gated decision.

Fields the audit needs and how they are reached:

| Need | Where it comes from |
| --- | --- |
| `extendedProperties.private` (the `cron.syncOriginal*` tuple) | already in the raw `events.list` passthrough — no projection strips it |
| `recurringEventId`, `originalStartTime` | same; retained verbatim in every candidate row |
| cancelled events excluded | `showDeleted=false` at the API, re-checked on `status` locally |
| pages beyond the first | **added:** `pageToken` on `list_events`, and bounded auto-pagination inside the audit |
| narrow to one source event | **added:** one `privateExtendedProperty` constraint. The Calendar API allows the parameter repeated; the UC `http_request` transport carries `params` as a string→string **map**, which cannot express a repeated key — so one constraint is reachable and the exact three-key match is enforced locally by `source_tuple`. |
