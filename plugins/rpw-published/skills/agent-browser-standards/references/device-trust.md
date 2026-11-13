# Device-trust IdPs: the exception to the separate-binary rule

Some identity providers admit only a **managed Google Chrome** (Okta + Chrome Enterprise
device trust is the common case). They refuse Chrome for Testing, Chromium, Electron, and
embedded panes, and that is a security control, not a bug to route around. For those apps
the *binary* rule yields. **The *profile* rule never does:**

- Run the system Google Chrome as a **second instance** on its own `--user-data-dir`, with
  `--remote-debugging-port` on loopback. Machine-level browser management still applies to
  that instance, so device signals flow; the human's daily windows are a separate process
  tree.
- Launch headed **without activating it** (`open -g -n -a "Google Chrome" --args …` on
  macOS). Open tabs with CDP `Target.createTarget {background: true}`. Never bring a page to
  the front; ask the human to switch tabs when they need to look.
- Add `--disable-backgrounding-occluded-windows --disable-renderer-backgrounding` so a
  window nobody looks at keeps running.
- Never `--disable-extensions`: policy-forced extensions are often what supply the device
  signals. Never cookie-copy into another browser to dodge the check.
- Identify and kill it by its profile path (`pkill -f -- "--user-data-dir=<dir>"`), since
  the process name matches the daily browser.

In this repo, `rpw browser start|stop|status|endpoint|open|tabs` does all of the above and
records the CDP port in `~/.rpw/ports.json`. Point any CDP client at `rpw browser endpoint`:
`agent-browser --cdp <port>`, `chrome-devtools-mcp --browser-url <url>`, or Playwright
`connectOverCDP`.
