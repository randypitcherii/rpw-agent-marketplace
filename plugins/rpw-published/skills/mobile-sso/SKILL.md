---
name: mobile-sso
description: Complete the agent's browser-based CLI authentication when the user operates Omnigent from a phone or another device. Use for a clickable SSO link, a returned localhost callback URL, or a browser that opened on the inaccessible agent host. Covers the agent's own login, not application auth implementation or mobile app installation.
---

# Mobile SSO

A browser on the agent host does not help a user on a phone.
The phone's `localhost` is not the agent host, so the final redirect can fail after successful SSO.

**Run the login yourself. Give the user its clickable link, accept the callback, and resume the original task.**

```text
Agent host: start CLI login → User's phone: open SSO link
Agent host: deliver callback ← User's phone: paste localhost URL
Agent host: check identity → Resume the blocked task
```

## 1. Start one login and retain its context

Use the service and profile required by the original task.
Check the installed CLI's help for its browser-suppression option and login timeout.
Verified with Databricks CLI 1.15.0 on macOS: this command printed the authorization URL without opening a browser.

```bash
BROWSER=/usr/bin/false databricks auth login --profile "$profile" --timeout 30m </dev/null
```

Run it with the harness's persistent process/session facility.
**Retain the process handle, profile, start time, authorization URL, and expected callback context across turns.**
An ordinary tool timeout must not kill the login when the turn ends.
The browser callback does not need stdin for this Databricks flow.
Do not generalize that property or `BROWSER` support to every CLI.

- **One owned attempt:** reuse your pending login when its URL is available.
  If replacement is necessary, cancel only the attempt you started.
  Never kill another session's login or all processes with a matching name.
- **Actual callback:** parse `redirect_uri` and `state` from that attempt's authorization URL.
  Keep the selected port and path. Occupied ports can change the listener.
  Never assume a particular port or edit the redirect URI.
- **Original OAuth context:** keep the CLI alive on the same host.
  The CLI retains its PKCE verifier and exchanges the code itself.
  Never construct a replacement authorization URL or exchange the code manually.
- **Minimal exposure:** avoid debug logging, browser-history inspection, and token dumps.
  Do not copy authorization URLs, callback URLs, or credentials into files, issues, PRs, or memory.

If the authorization URL or callback context is unavailable, stop this procedure.
Use the provider's documented alternate flow instead of guessing.

## 2. Send a clickable link, then yield

Check that the authorization URL belongs to the expected service.
Send the exact URL printed by the active CLI as a Markdown link.
Do not place the link in a code block or substitute a generic workspace login page.

Use this shape, with the actual URL, callback destination, and remaining timeout:

> [Sign in to SERVICE](<AUTHORIZATION_URL>)
>
> After signing in, paste the full `http://localhost:PORT/...` callback URL here—even if the page fails to load.
> This login request expires in **N minutes**.

The displayed destination must match the actual redirect URI, including a non-root callback path.
Explain that the callback contains a short-lived login code.
Request it only in the user's private, access-controlled conversation with this agent.
Never request passwords, MFA codes, access tokens, or refresh tokens.
If this conversation is shared, do not ask the user to paste the callback there.

**Yield while the user completes SSO.** Do not repeatedly poll a silent process.
When concurrent work requires a status check, space checks at least 30 seconds apart.
Do not restart a healthy login because the user has not replied yet.

## 3. Check the callback before any request

First check whether your login already completed through a local browser callback.
If authentication already succeeded, skip callback delivery and proceed to the identity check.
Otherwise, require a live, owned login attempt and check the submitted URL with a URL parser:

| Check | Required result |
|---|---|
| Destination | The scheme, hostname, effective port, and path match this attempt's `redirect_uri`. Treat an empty path as `/`. |
| Loopback only | HTTP with exactly `localhost`, `127.0.0.1`, or IPv6 `::1`. Reject other hosts, userinfo, fragments, and control characters. |
| State | Exactly one nonempty `state`, equal to this attempt's expected value after query parsing. Reject duplicate response parameters. |
| Response | Exactly one nonempty `code`, with no OAuth `error`. Fixed redirect query parameters must match. Preserve any provider `iss`. |
| Freshness | The process is still waiting, within its timeout, and this callback has not already been delivered. |

**Do not forward an arbitrary pasted URL.**
If the destination or state differs, make no network request and report the mismatch without repeating the code.
If context is missing or expired, offer one fresh login attempt instead of trying other listeners.
If OAuth returns an error, report its non-sensitive error identifier and stop before forwarding.

After these checks, deliver the **original, unchanged URL** once from the same host as the CLI.
Use a safely assigned shell variable or a tool argument, not interpolated shell syntax.
For example, after assigning the checked URL to `callback_url`:

```bash
curl --disable --silent --show-error --globoff \
  --noproxy '*' --proto '=http' --max-redirs 0 \
  --connect-timeout 5 --max-time 15 \
  --output /dev/null --write-out 'HTTP %{http_code}\n' \
  --url "$callback_url"
```

Keep `--disable` first to ignore local curl configuration.
Do not add `--location`, retries, tracing, or verbose output.
The request must bypass proxies and must not follow redirects.
Do not bind a new public listener, open a firewall port, or rewrite `localhost` to a LAN address.

If delivery fails, check the owned CLI's status before doing anything else.
Do not replay a possibly consumed code automatically.
A callback HTTP response alone does not prove authentication.

## 4. Check authentication and resume

Collect the original login process result.
Require successful completion, then run the provider's non-secret identity/status command.
For Databricks:

```bash
databricks auth describe --profile "$profile"
```

Check the expected user, host, and profile in its output.
Do not rely only on its exit code: it can exit zero while reporting an authentication error.
Do not run commands that print tokens.

**Retry the operation that required authentication.**
For a blocked read, run the same read again.
For a write with an uncertain prior outcome, check whether it succeeded before retrying.
Preserve existing approval requirements for the original task.
Do not ask the user whether login worked or ask them to repeat the original request.

## Boundaries

- **Device-code flows:** use the provider's verification URL and user code. There is no localhost callback to relay.
- **Other browser CLIs:** inspect their documented flow first. Do not assume Databricks flags, stdin behavior, or response parameters apply.
- **Application auth implementation:** use `reauth-before-error`. This skill operates the agent's own credentials, not software under development.
- **Mobile installation problems:** this is not an Omnigent app-install or device-management troubleshooting procedure.
