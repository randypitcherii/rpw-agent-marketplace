---
name: browser-testing-standards
description: The house way to test a web UI — a three-tier ladder (unit test → node DOM harness → headless Chrome over CDP from the native test runner) and the rules that keep browser suites inside CI, not beside it. Use when adding, porting, or reviewing e2e tests for a web surface, picking a browser automation tool, or wiring a UI suite into CI. Trigger on "e2e test", "browser test", "Playwright", "Selenium", "Cypress", "headless Chrome", "test this UI", "flaky e2e".
---

# Browser Testing Standards

The house standard for testing a web surface. One rule dominates everything else: **a browser
suite that is not in the default gate is not coverage.** The suite this standard came from
A browser suite that sat outside CI for months quietly rotted to seven red specs while the
app kept shipping — the page moved its panels behind tabs and nothing said so.

Everything below exists to make "inside the gate" the cheap option.

**Scope boundary:** this skill governs *test architecture* — which rung a test belongs on and how
the suite stays in CI. Which browser an **agent** drives interactively, and how it launches
(dedicated binary, isolated agent-owned profile, headless, accessibility snapshots), is
`agent-browser-standards`. Read that one when wiring a browser MCP server or automating a web UI
that has no API.

## The ladder — pick the lowest rung that can hold the test

| Rung | Tool | Covers | Cost |
|---|---|---|---|
| 1. Logic | Plain unit test in the app's language | Pure functions, reducers, formatting, server handlers | ~0 |
| 2. Page script | **node DOM harness** — run the page's own `<script>` against hand-rolled fake elements | Render functions, event handlers, focus management, "does this JS even parse" | node only |
| 3. Assembled app | **Headless Chrome over CDP, driven from the native test runner** | Real server wiring, CSS-driven visibility, native dialogs, canvas layout, console-error-free load | the browser already on the box |

Rung 2 is underused and very strong: extract the script block, `node --check` it, then execute
it with a small fake `document`. It needs no server, no port, and no browser, so it belongs in
the fast tier. Reach for rung 3 only for what genuinely needs a rendering engine.

## Rung 3: the driver

**Drive the installed Chrome over the DevTools Protocol from the test runner you already have.**
Not a second runner, not a downloaded browser.

- **No browser download.** GitHub-hosted Ubuntu images ship `google-chrome` and `chromium`;
  dev machines have Chrome. Discover it (`CHROME_PATH` override → PATH → platform paths).
  Playwright's `playwright install chromium` costs ~430 MB per environment for a browser that
  is already there. **On a machine that already has an automation binary** (Chrome for Testing,
  per `agent-browser-standards`), point `CHROME_PATH` at it — same zero-download rule, but the
  suite stops sharing process and app identity with the human's Chrome, which is how a test run
  ends up writing OS-level state the human sees (#1058).
- **No second test runner.** A CDP client is a WebSocket plus JSON — small enough to own
  (~350 lines) and it keeps the suite as ordinary test functions in the default invocation.
- **Assert the browser exists.** Missing browser = hard failure under `CI`, loud skip locally.
  A silent skip is how a suite stops running without anyone noticing.

A reference implementation can keep `cdp.py` as the whole driver; its README
carries the measured tool comparison).

**When Playwright is still right:** a real cross-browser matrix (Firefox/WebKit), or a team
leaning on trace-viewer debugging. Both are rare for an internal single-surface app. Decide with
numbers, and if you keep it, wire it into CI — never leave it beside CI.

## Rules for the suite itself

- **Offline fake server.** The suite starts the app's real server composition with every external
  dependency swapped for an offline fake, on an ephemeral port it picked. No shared fixed port,
  no live credentials, no "reuse whatever is running" ambiguity by default.
- **No fixed sleeps.** Every wait polls a condition against a deadline. A `sleep(500)` either
  wastes half a second or hides a race; usually both. Replace `networkidle`-style heuristics with
  something you can defend — e.g. count in-flight `fetch` calls with a wrapper installed before
  any page script runs.
- **Poll compound conditions together.** If a control updates a label and a status line from
  separate async paths, assert them in ONE predicate. Asserting in sequence catches the
  in-between state and produces exactly the flake that makes people delete browser suites.
- **Fresh tab per test; restore shared state.** Tests share one server process, so any test that
  toggles server state puts it back.
- **Kill what you spawn.** Server and browser both die in a fixture teardown that runs on
  failure too.

## Reviewing a UI test PR

1. Is the suite in the default gate command, or beside it?
2. Could this test have been rung 1 or 2?
3. Any fixed sleep, any hardcoded port, any network call that is not the app under test?
4. Does a missing browser fail CI, or skip it?
5. Do the assertions describe user-visible behavior, or the current DOM's incidental shape?
