# CI preflight — before a browser test becomes required

Companion to [SKILL.md](SKILL.md). Read this **before** adding a rung-3 (headless browser) test to
the default gate.

## The two failure modes, and why both are bad

A rung-3 test needs a browser binary on the runner. There are exactly two ways to get that wrong:

- **Required test, absent browser → a red gate for everyone**, on a change that has nothing to do
  with the UI. The next person's fix is to delete the test.
- **Silent skip → the suite stops running and nobody notices.** This is the failure
  `browser-testing-standards` was written from: `projects/high-voltage/e2e/` rotted to 7 red specs
  while the app kept shipping, because the page moved its panels behind tabs and nothing said so.

The preflight exists so you choose deliberately instead of finding out on someone else's PR.

## The preflight

Run all three before you make the test required.

1. **Does the rung-3 test need to exist at all?** Rung 1 (unit) and rung 2 (node DOM harness against
   the page's own script) cover render functions, event handlers, and focus management with no
   browser and no port. Overflow-at-a-viewport and CSS-driven visibility genuinely need a rendering
   engine; "does this JS parse" does not.

2. **Is the binary discoverable on every environment that runs the gate?**

   ```sh
   # locally and on the runner image
   echo "${CHROME_PATH:-<unset>}"
   command -v google-chrome chromium chromium-browser 2>/dev/null
   ```

   Discovery order is `CHROME_PATH` → `PATH` → platform paths, and it must not download a browser.
   On a machine with an automation binary, point `CHROME_PATH` at it so the run does not share
   process and app identity with the human's browser.

3. **Does absence fail loudly where it must, and skip loudly where it may?** Under `CI`, a missing
   browser is a **hard failure** — a skip there is the silent-rot mode above. Locally it is a
   **loud skip** that names the binary it looked for. Both behaviors are themselves tested.

## If any preflight fails

Add the test, but **not to the required gate**. Wire it into an explicitly-invoked target, say in
the PR body which rung it sits on and why it is not required yet, and file the issue for making it
required. A test beside the gate that is *labeled* beside the gate is honest; one that silently
skips inside it is not.

## Scope

This page covers the *preflight decision*. Driver architecture, suite hygiene (no fixed sleeps, no
hardcoded ports, offline fake server, fresh tab per test), and the UI-test review checklist all live
in `browser-testing-standards` — read it for the how.
