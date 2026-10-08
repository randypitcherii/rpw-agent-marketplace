---
name: agent-browser-standards
description: How to give an agent a browser — dedicated automation binary, isolated agent-owned profile, headless, snapshots over screenshots. Use when wiring browser automation into an agent, configuring a browser MCP server, driving a web UI with no API, auto-approving browser tools, or when agent tabs collide with the human's Chrome. Trigger on "browser MCP", "Playwright MCP", "agent browser", "Chrome for Testing", "headless browser". NOT e2e test architecture — see browser-testing-standards.
---

# Agent Browser Standards

An agent that drives the human's daily Chrome is a shared-state bug generator: agent tabs
interrupt a working session, human-clicked links land in the agent's window, both processes
report as "Chrome" so neither can be killed or launched on purpose, and the agent inherits
every login, extension, and autofill entry the human has. Screenshot-based page reading then
adds ~3,000–5,000 tokens per look at a page that a snapshot describes in ~300.

**The standard: a separate browser binary, an agent-owned profile, headless, snapshots.** Each
of the four is independently load-bearing.

## Rule 0 — the agent never touches the daily browser

Two distinct things must both be separate, and they fail differently:

- **The profile** (logins, cookies, history). Sharing it is the security failure. Never
  `--user-data-dir` at `~/Library/Application Support/Google/Chrome`, and never attach to a
  running daily browser over `--cdp-endpoint` / `--browser-url`.
- **The binary** (process and app identity). Sharing it is the operational failure — same
  process name, same app icon, same OS-level handlers, so `pkill`, Raycast, and "open this
  link" can't tell the two apart. It is also how automation writes OS state the human sees
  (#1058: e2e Chrome launches creating Web App shortcuts).

Use **Chrome for Testing** or Playwright's bundled Chromium. Both carry their own name
(`Google Chrome for Testing`), can never become the system default browser, and are killable
on purpose: `pkill -f "Chrome for Testing"`.

## Pick a configuration

| You need | Profile | Config |
|---|---|---|
| Validate a web change, read a page, scrape docs | throwaway | `--isolated --headless` |
| Recurring UI-only ops that need a login (no API available) | agent-owned, persistent | `--user-data-dir=~/.agent-browser/profile --headless` |
| Same, but portable / seeded from a saved session | throwaway + seed | `--isolated --storage-state=~/.agent-browser/state.json` |
| A human to watch, or to complete 2FA once | agent-owned | drop `--headless`, same profile |
| 10+ interactions in one session | either | escalate to the Playwright CLI (below) |

Default to the first row. Persistence is a commitment to holding live credentials on disk —
take it only when the work genuinely recurs.

## Reference MCP configs

**Isolated (the default).** Throwaway in-memory profile, discarded at exit:

```json
{
  "mcpServers": {
    "agent-browser": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--isolated", "--headless"]
    }
  }
}
```

**Pinned to Chrome for Testing.** Same isolation, plus distinct process identity — use when
the site needs real Chrome rather than Chromium, or when you need to kill it by name:

```json
{
  "mcpServers": {
    "agent-browser": {
      "command": "npx",
      "args": [
        "@playwright/mcp@latest", "--isolated", "--headless",
        "--executable-path", "/Users/<you>/.agent-browser/chrome/mac_arm-<version>/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
      ]
    }
  }
}
```

**Persistent agent profile.** For login continuity; register it as a *separate* server so the
isolated one stays the default and this one is chosen deliberately:

```json
{
  "mcpServers": {
    "agent-browser-logged-in": {
      "command": "npx",
      "args": [
        "@playwright/mcp@latest", "--headless",
        "--user-data-dir", "/Users/<you>/.agent-browser/profile",
        "--allowed-origins", "https://app.example.com"
      ]
    }
  }
}
```

Install, bootstrap the login, and wire auto-approval per
[setup.md](setup.md). Flags move between releases — confirm with
`npx @playwright/mcp@latest --help` before trusting a flag list, including this one.

### Per harness

The `mcpServers` block is portable; the file it lands in is not.

| Harness | Config file | Tool the agent calls |
|---|---|---|
| Claude Code | `~/.claude.json` | `mcp__agent-browser__browser_snapshot` |
| Pi | `~/.config/mcp/mcp.json` — **no native MCP**, needs the `pi-mcp-adapter` extension | `agent_browser_browser_snapshot`, via Pi's single `mcp` proxy tool |

Per-harness install, precedence, and verification: [setup.md](setup.md).

## Headless by default

Headed costs a window that steals focus, a compositor, and a screenshot habit. Go headed only
to **watch a flow you are debugging** or to **complete an interactive auth step** (2FA, SSO
consent) — then go back. With a persistent profile the login survives the switch, so the
headed run happens once and every later run is headless.

## Snapshots, not screenshots

`browser_snapshot` returns the accessibility tree: roles, names, and a `ref` per element that
`browser_click` / `browser_type` accept directly. It is both cheaper and more actionable than
an image, which an agent must still describe in words before it can act.

| Reading a page | Tokens | Use when |
|---|---|---|
| Accessibility snapshot | ~200–400 | Always — it is also what you click against |
| Screenshot | ~3,000–5,000 | Visual-only questions: layout, CSS, rendering, a canvas |

**Escalation for long sessions:** a 10+-interaction session over MCP costs ~114K tokens,
because every step round-trips a snapshot through the context window. The same work as a
**Playwright CLI script** costs ~27K — the loop runs inside the script and only the result
comes back. Rule of thumb: exploration and one-off validation over MCP, repeated or long
deterministic flows as a script (which is then also reviewable, committable, and rerunnable).
Keep screenshots to `--output-dir` on disk and read them only when a question is genuinely
visual.

## Auto-approve the sandbox, not the credentials

An isolated headless browser on a throwaway profile can't damage anything the human owns, so
prompting for each navigation buys nothing and trains the human to click through. Auto-approve
that server; keep the logged-in one gated.

```json
{
  "permissions": {
    "allow": ["mcp__agent-browser"]
  }
}
```

The persistent-profile server is a different risk class: it holds real sessions and can take
real actions as that account. Leave it prompting, and fence it with `--allowed-origins`.

**Pi inverts the default.** `pi-mcp-adapter` is allow-by-default, so the isolated server
satisfies this rule with no config — but the logged-in one is ungated until you add
`"approveTools": true` to that server entry. A gated call then fails closed with
`approval_required` in headless `pi -p` runs, which is why unattended work uses the isolated
server.

## Security rules

- **Least-privilege agent accounts.** Where an agent needs a login, give it its own account
  with the narrowest role that works — not the human's SSO session. Revoking one account
  must not disrupt the human.
- **Session state is a secret.** `--storage-state` files and persistent profiles hold live
  cookies. Keep them under `~/.agent-browser/` (`chmod 600`), never in a repo, never committed.
- **Fence the origins** for any logged-in configuration (`--allowed-origins`), so a prompt
  injection on a page can't drive the authenticated browser somewhere else.
- **No `--no-sandbox`** unless a container forces it, and never combined with a logged-in
  profile.

## Troubleshooting — a hostname check rejects `localhost` (human-authorized only)

⚠️ **This is a documented exception, not a default. An agent may not use it on its own
initiative.** It is written down so that when a human chooses it, they choose it knowingly.

Some embedded agent browsers — the Omnigent one among them — block model-issued navigation to
loopback and private hosts on purpose, as an SSRF and local-data-exfiltration defense. That
block makes previewing a local preview server impossible: `http://localhost:<port>` is
rejected outright.

`lvh.me` is a public DNS name whose A record is `127.0.0.1`, so `http://lvh.me:<port>/<path>`
reaches the *same* local service while presenting a non-loopback hostname. Two consequences,
both load-bearing:

- **The content stays local.** The TCP connection goes to `127.0.0.1`; no page bytes leave
  the machine.
- **The DNS lookup does not.** Resolving `lvh.me` is an external query, so the hostname and
  the fact that you are previewing something are visible to your resolver — and a wildcard
  subdomain leaks whatever you put in front of it.

**Conditions on use — all of them, every time:**

1. 🚫 **Never agent-initiated.** A human must explicitly authorize this navigation for *this*
   preview. Prior authorization does not carry over to the next session or the next port.
2. Bind the preview server to loopback only (`127.0.0.1`, not `0.0.0.0`), and stop it when the
   preview is done.
3. Never put a secret, a customer name, or anything else sensitive in the subdomain — the
   subdomain goes out with the DNS query. The URL path does not enter DNS, but it is still
   visible to the local preview service and browser history/logging.
4. Serve only content you were going to look at anyway. This is a viewing shortcut, not a way
   to reach a service the block was protecting.

**Temporary, pending upstream.** This works only because the check is hostname-based rather
than resolution-based; it is a gap, not a feature. It is reported upstream as
[GHSA-46gw-v2v7-rj33](https://github.com/omnigent-ai/omnigent/security/advisories/GHSA-46gw-v2v7-rj33).
**When upstream closes the hostname-only gap, delete or rewrite this section** — do not keep
it as folklore, and do not go looking for the next alias that happens to resolve to
`127.0.0.1`. The supported path is publishing the preview, or an upstream-sanctioned local
preview mechanism.

## Relationship to the other browser standards

- **`browser-testing-standards`** governs e2e *test architecture* — the unit → DOM-harness →
  headless-Chrome-over-CDP ladder and keeping suites inside the gate. It says "don't download a
  browser," and that stands for suites driving the already-installed Chrome. This skill governs
  which browser an *agent* gets; there the separate binary is the deliverable, not overhead.
  A suite that writes OS-level state should still point `CHROME_PATH` at the automation binary.
- **`chrome-devtools-mcp`** (a plugin dependency) is the right tool for performance traces and
  DevTools-domain work. Its `--browser-url` attach mode targets a running browser — never point
  it at the daily one.
