# Agent Browser Setup

Mechanics for the standard in [SKILL.md](SKILL.md): installing the automation binary, wiring
the MCP servers, bootstrapping a login, proving the isolation is real, and the failure modes
that mean it isn't.

Everything lives under one directory the agent owns:

```
~/.agent-browser/
├── chrome/          # Chrome for Testing install
├── profile/         # persistent agent profile (live cookies — chmod 700)
├── state.json       # saved storage state (live cookies — chmod 600)
└── out/             # screenshots / traces the agent writes
```

## 1. Install a dedicated browser binary

**Chrome for Testing** (separate app name and icon, can never become the system default):

```bash
mkdir -p ~/.agent-browser
npx @puppeteer/browsers install chrome@stable --path ~/.agent-browser/chrome
```

It prints the resolved binary path — keep it; that string is the `--executable-path` value.
On Apple silicon it looks like:

```
~/.agent-browser/chrome/mac_arm-<version>/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing
```

**Playwright's bundled Chromium** is the zero-config alternative — no `--executable-path`
needed, and `--browser=chromium` (the default) picks it up:

```bash
npx playwright install chromium
```

Pick Chrome for Testing when the target site needs real Chrome (DRM, a Chrome-only API, a
user-agent check) or when process identity matters for killing and launching. Otherwise
Chromium is fine and smaller to reason about.

## 2. Register the MCP servers

Two servers, deliberately distinct — the isolated one is the default, the logged-in one is a
choice:

```bash
# default: throwaway profile, headless
claude mcp add agent-browser --scope user \
  -- npx @playwright/mcp@latest --isolated --headless

# only if recurring UI-only work needs a login
claude mcp add agent-browser-logged-in --scope user \
  -- npx @playwright/mcp@latest --headless \
     --user-data-dir "$HOME/.agent-browser/profile" \
     --allowed-origins "https://app.example.com"
```

Add `--executable-path "<path from step 1>"` to either to pin Chrome for Testing. For
harnesses configured by file rather than CLI, the equivalent JSON blocks are in
[SKILL.md](SKILL.md).

### Pi — install the MCP bridge first

Pi has no MCP client of its own, so registering a server is two moves: install the adapter
extension, then write the config file it reads.

```bash
pi install npm:pi-mcp-adapter
```

That appends `npm:pi-mcp-adapter` to `"packages"` in `~/.pi/agent/settings.json` and installs
under `~/.pi/agent/npm/`. Add `-l` to scope it to the current project instead
(`.pi/settings.json` + `.pi/npm/`). **Restart Pi** — extensions load at startup.

Then write both servers into the user-global config (create the directory if it is new):

```bash
mkdir -p ~/.config/mcp
cat > ~/.config/mcp/mcp.json <<'JSON'
{
  "mcpServers": {
    "agent-browser": {
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest", "--isolated", "--headless"]
    },
    "agent-browser-logged-in": {
      "command": "npx",
      "args": [
        "-y", "@playwright/mcp@latest", "--headless",
        "--user-data-dir", "/Users/<you>/.agent-browser/profile",
        "--allowed-origins", "https://app.example.com"
      ],
      "approveTools": true
    }
  }
}
JSON
```

Drop the second entry until step 3 has actually bootstrapped a login — an unseeded persistent
profile is just a slower isolated one. `approveTools` is explained in step 4.

Restart Pi (or `/mcp reconnect agent-browser` in a live session) and confirm:

| Command | Expect |
|---|---|
| `/mcp` | `agent-browser` listed, `enabled` |
| `/mcp tools` | `agent_browser_browser_navigate`, `agent_browser_browser_snapshot`, ~24 total |
| `/mcp setup` | which config paths actually loaded — the first thing to check when an edit seems ignored |

`agent-browser` **not** appearing means the adapter did not load: check that
`~/.pi/agent/settings.json` lists `npm:pi-mcp-adapter` in `"packages"` and that you restarted.
`agent-browser` listed but with no tools is normal before the first call — servers are lazy, so
the browser process starts on demand.

The adapter exposes **one** `mcp` proxy tool (~200 tokens) rather than 24 tool definitions, and
derives each name from `toolPrefix` (default `"server"`): server name + tool name, hyphens
becoming underscores, so `agent-browser` + `browser_snapshot` = `agent_browser_browser_snapshot`.
`/mcp tools` prints the exact names. Config is read from six paths, later winning over earlier:
`~/.config/mcp/mcp.json`, `~/.agents/mcp.json`, `~/.agents/mcp/mcp.json`,
`~/.pi/agent/mcp.json`, `./.mcp.json`, `./.pi/mcp.json`.

To try the whole thing without touching your live setup, point `PI_CODING_AGENT_DIR` at a
scratch directory (`PI_CODING_AGENT_DIR=/tmp/pi-trial pi install npm:pi-mcp-adapter`, config at
`/tmp/pi-trial/mcp.json`) — nothing under `~/.pi/` is read or written.

## 3. Bootstrap a login once, headless forever after

Only for the persistent-profile server. Run it **headed** once so a human can complete the
password and 2FA in a visible window; the profile keeps the session afterwards.

```bash
npx @playwright/mcp@latest --user-data-dir "$HOME/.agent-browser/profile"
```

Drive it to the login page from the agent, hand the window to the human for credentials and
2FA, then stop the server. Every later run uses the same `--user-data-dir` with `--headless`
and is already logged in.

For a **portable seed** instead of a whole profile, save storage state with a short script and
point `--storage-state` at it:

```js
// save-state.mjs — run with: node save-state.mjs
import { chromium } from 'playwright';

const browser = await chromium.launch({ headless: false });
const ctx = await browser.newContext();
await (await ctx.newPage()).goto('https://app.example.com/login');
console.log('Log in in the browser window, then press Enter here.');
await new Promise((r) => process.stdin.once('data', r));
await ctx.storageState({ path: `${process.env.HOME}/.agent-browser/state.json` });
await browser.close();
```

```bash
chmod 600 ~/.agent-browser/state.json && chmod 700 ~/.agent-browser/profile
```

Both artifacts hold live session cookies. Treat them exactly like a credential file: outside
any repo, never committed, rotated by deleting them and repeating this step.

## 4. Auto-approve the isolated server

Isolated + headless + throwaway profile has nothing to damage, so per-call prompts only teach
the human to click through. Allow the whole server:

```json
{
  "permissions": {
    "allow": ["mcp__agent-browser"]
  }
}
```

Put it in `~/.claude/settings.json` for every project, or a project's
`.claude/settings.json` to scope it. Single tools work too
(`mcp__agent-browser__browser_navigate`) but the point is to stop prompting for a sandbox.

Harnesses with their own permission UI (e.g. Raycast tool permissions) get the same
treatment: auto-approve the isolated server by name, leave `agent-browser-logged-in`
prompting.

**Pi needs the opposite edit.** `pi-mcp-adapter` prompts for nothing unless `approveTools`
says so, so the isolated server is already auto-approved — the work is *gating* the logged-in
one, which is the `"approveTools": true` line in the step-2 config. Verify by calling
`mcp({ tool: "agent_browser_logged_in_browser_navigate", args: { url: "https://app.example.com" } })`:
Pi should offer **Allow once / Allow for session / Deny**, while the same call against
`agent_browser_browser_navigate` runs unprompted. (`/mcp tools` prints the exact prefixed
names — the server name's hyphens become underscores.) In a headless run (`pi -p`) the gated call
returns `approval_required` and does not execute — expected, and the reason unattended work
uses the isolated server.

## 5. Prove the isolation

Three checks, all cheap, and worth running once per machine plus any time a config changes:

```bash
# the automation binary is what is running (and the daily Chrome is untouched)
pgrep -fl "Chrome for Testing" ; pgrep -fl "Google Chrome.app"

# no launched instance points at the human's profile.
# `pgrep`, not `ps`: /bin/ps is denied in some agent sandboxes (#1785), and
# `pgrep -f` matches the full command line so the flag is never truncated.
pgrep -fl -i chrome | grep -o -- "--user-data-dir=[^ ]*" | sort -u

# nothing writes into the daily profile
ls -la ~/Library/Application\ Support/Google/Chrome/Default/Cookies
```

The second must never print a path under `Application Support/Google/Chrome`. Then have the
agent `browser_navigate` + `browser_snapshot` a page: it should return a tree, with no window
appearing anywhere on screen.

In **Claude Code** that is `browser_navigate` then `browser_snapshot`. In **Pi** it is the same
two calls through the proxy tool:

```
mcp({ tool: "agent_browser_browser_navigate", args: { url: "https://example.com" } })
mcp({ tool: "agent_browser_browser_snapshot", args: {} })
```

A passing run returns an accessibility tree (`heading "Example Domain"` and a link node) in a
few hundred tokens, no window appears, and while the call is in flight the three checks above
still show a `--user-data-dir` under `/var/folders/…` or nothing at all — never one under
`Application Support/Google/Chrome`. Clean up after a manual check: `pkill -f "@playwright/mcp"`
(plus `pkill -f "Chrome for Testing"` if you pinned the binary).

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Agent tabs open in the human's Chrome | Server attaching to a running browser (`--cdp-endpoint` / `--browser-url`), or a `--user-data-dir` pointing at the daily profile | Switch to `--isolated`; never attach to the daily browser |
| Can't tell which Chrome to kill or launch | Automation is using the daily binary | Pin `--executable-path` to Chrome for Testing; `pkill -f "Chrome for Testing"` |
| Automation created Web App shortcuts / changed OS handlers | Same shared binary (#1058) | Same fix — dedicated binary, and set `CHROME_PATH` for CDP-driven suites |
| Login gone on every run | `--isolated` with no seed | Persistent `--user-data-dir`, or `--storage-state` from step 3 |
| Session burns 100K+ tokens | Screenshots in the interaction loop, or a long MCP session | Snapshots only; escalate 10+-interaction flows to a Playwright CLI script |
| Headless run fails where headed worked | Bot detection or a viewport-dependent layout | Set `--viewport-size`, or run that one flow headed — do not fall back to the daily browser |
| Flag rejected on startup | Flags move between `@playwright/mcp` releases | `npx @playwright/mcp@latest --help` |
| Pi: no `agent-browser` in `/mcp` | Adapter not installed or Pi not restarted | `pi install npm:pi-mcp-adapter`, check `"packages"` in `~/.pi/agent/settings.json`, restart |
| Pi: config edits ignored | A later file in the precedence chain overrides it (`.mcp.json` / `.pi/mcp.json` beat `~/.config/mcp/mcp.json`) | `/mcp setup` shows which paths loaded; remove the project-local duplicate |
| Pi: logged-in browser runs with no prompt | `approveTools` missing — the adapter is allow-by-default | Add `"approveTools": true` to that server entry |
