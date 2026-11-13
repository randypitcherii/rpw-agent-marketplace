# slack-browser — details

## Prior art, and why this differs

| Project | Auth | What it does with the session |
|---|---|---|
| [`korotovsky/slack-mcp-server`](https://github.com/korotovsky/slack-mcp-server) "stealth mode" | `xoxc` + `xoxd` from the browser | Copies both into env vars. Its auth doc gives the token lookup this helper runs in the page: `JSON.parse(localStorage.localConfig_v2).teams[<TEAM>].token` |
| [`rusq/slackdump`](https://github.com/rusq/slackdump) "EZ-Login 3000" | Browser-driven login | Stores the extracted credentials for later exports |
| This skill | The live tab | Never copies them: each call is a `fetch` inside the signed-in page |

The two projects above are the right tools for a long-running server or a full archive. Both
need the credentials outside the browser, so get the human's OK before using them.

## How a call works

1. `rpw browser endpoint` gives the CDP base URL; `/json/list` finds the
   `app.slack.com/client/<TEAM>` tab.
2. One `Runtime.evaluate` per batch of calls: read `localConfig_v2.teams[TEAM].token`, then
   POST same-origin `https://app.slack.com/api/<method>` with the token in the form body. The
   `d` cookie goes along on its own (`credentials: "include"`). Do not use the workspace host
   (`teams[TEAM].url`, `https://<name>.slack.com/`): from the app.slack.com page that request
   fails CORS (`TypeError: Failed to fetch`), even though the web client's own traffic goes there.
3. `users.info` lookups for the authors and mentions on a page are batched into one evaluate.

## Enterprise Grid (#2717)

A grid client redirects `app.slack.com/client/<T…>/<C…>` to `app.slack.com/client/<E…>/<C…>`,
where `E…` is the enterprise id. `localConfig_v2.teams` still keys the workspace by `T…` (with
`enterprise_id: "E…"`) and also holds an entry for the `E…` itself.

- With `--team T…`, a tab whose URL names the `T…` is used directly (non-grid path, no storage
  read). Otherwise each `app.slack.com/client/` tab's team map is read (ids and a has-token flag
  only, never the token) and a tab on `/client/<T…>` or `/client/<enterprise_id>` is picked.
- With `--team E…`, the one `T…` under that enterprise is used for the token. Several workspaces
  under one grid exit 2 and list them; pass the `T…`.
- Logic lives in `scripts/tab_match.mjs` (pure, unit-tested in `tests/test_slack_browser_skill.py`).

**`slack` MCP rate limit.** The MCP's `conversations.history` / `conversations.replies` allow
roughly one call a minute. On any workspace the agent Chrome is signed into,
`history` and `thread` here run as the user's own web session at the client's normal tier.

## Beyond text

- **Files:** `files.info file=F…` returns `url_private`. Fetch it inside the page the same way,
  since the cookie authenticates it. For a one-off, a screenshot of the open tab is simpler.
- **Visual questions** (how a canvas or an attachment looks): `browser_snapshot` or a screenshot
  against the same tab.
- **Many channels:** `conversations.list types=public_channel,private_channel` is a raw call.
  Shared (Slack Connect) channels show up under the host team's id.

## When it breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| exit 3 on a tab that looks signed in | Slack renamed `localConfig_v2` or moved the token | In the tab's console, find the key holding `xoxc-`, then update `pageFn` |
| `TypeError: Failed to fetch` / `http_404` on every method | Same-origin `app.slack.com/api/` stopped answering | Try `auth.test` against `location.origin` and the workspace host in the tab console; use whichever returns `ok` |
| `ratelimited` after back-off | Too many pages in a row | Narrow it with `oldest=` / `latest=` |
| `not_in_channel` | The account isn't a member of that channel | Ask the human; joining is a write |
