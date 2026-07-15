# iMessage MCP (`imsg` basic mode)

[FastMCP](https://github.com/jlowin/fastmcp) server wrapping the
[`imsg`](https://github.com/steipete/imsg) CLI by Peter Steinberger. Two deliberately
narrow capabilities (issue #284):

1. **Read-only message search** — recover context or surface forgotten tasks from your
   iMessage/SMS history.
2. **Send-only "notify-me" alerts** — let agents push a high-signal alert to *your*
   phone, and nowhere else.

## Why this shape

- **Basic mode only.** All commands work with just **Full Disk Access + Automation**
  permission. The server never invokes `imsg`'s advanced/IMCore bridge (react, edit,
  unsend, typing, launch). Those need **System Integrity Protection disabled** — we
  keep SIP **on**. `imsg status` should report *Basic features: Available*.
- **Search is strictly read-only.** The read path may only run `search`, `history`,
  and `chats` against `chat.db` — never a write/send subcommand.
- **Alerts are send-only and fixed-recipient.** `imessage_notify_me` takes no recipient
  argument; it can reach only the `NOTIFY_ME_HANDLE` configured at setup. A swarm of
  agents never gets broad iMessage read/write.

> `chat.db` read access exposes your entire message history (including 2FA codes).
> That's why search is read-only and the alert path can't read anything.

## Setup

1. Install the CLI and grant permissions:
   ```bash
   brew install steipete/tap/imsg
   imsg status   # expect: Basic features (send, receive, history): Available
   ```
   Grant your terminal/host app **Full Disk Access** and **Automation** in
   System Settings > Privacy & Security. Do **not** disable SIP.
2. Configure the alert recipient. Copy `template.env` to `dev.env` here (or to the
   stable path `~/.claude/mcp-servers/imessage/dev.env`) and set `NOTIFY_ME_HANDLE`
   to your own phone number (E.164) or iMessage email. `dev.env` is git-ignored —
   it holds your phone number; never commit it.

## Run

```bash
cd plugins/rpw-published/mcp-servers/imessage
APP_ENV=dev uv run python run_mcp.py
```

Merge `imessage.mcp.json` into your MCP client config (paths use `${CLAUDE_PLUGIN_ROOT}`).

## Tools

- `imessage_search` — search history for a phrase (read-only). `match`: contains|exact.
- `imessage_list_chats` — list recent conversations with their ids (read-only).
- `imessage_recent` — recent messages for a chat by id and/or participants, with
  optional ISO8601 time bounds (read-only).
- `imessage_notify_me` — send a text alert to the configured `NOTIFY_ME_HANDLE`
  (send-only, no recipient argument).

Errors are returned as JSON: `{"success": false, "error": "...", "detail"?: "...", "hint"?: "..."}`.

## Tests

```bash
cd plugins/rpw-published/mcp-servers/imessage
uv run python -m pytest test_mcp_imsg_shaping.py -v
```

These mock the `imsg` subprocess, so they need no Full Disk Access and send no real
messages. They assert: read tools only ever invoke `search`/`history`/`chats`,
limits are clamped, and `notify_me` always targets the configured handle and exposes
no recipient parameter.
