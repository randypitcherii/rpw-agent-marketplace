---
name: reauth-before-error
description: Use when building or reviewing auth/session handling in software — expired-credential detection, wrapping an OAuth/SSO CLI login (`sf org login web`, `databricks auth login`, `gcloud auth login`, `aws sso login`), `auth_expired` error envelopes, login banners, or session-restore UX. Trigger on "session expired", "reauth flow", "login banner", "auth error handling". NOT for the agent's own interactive auth during a session — this governs the software agents BUILD.
---

# Reauth Before Error

**An auth error must not reach the user until the software has first attempted the 99th-percentile fix: programmatically launching the reauth flow itself, so the only thing the human does is the browser SSO click-through.**

Expiring credentials are normal and reauth is often necessary. What is not acceptable is the lazy version — "your session expired, run `sf org login web` in a terminal, then retry." Every one of those login CLIs (`sf org login web`, `databricks auth login`, `gcloud auth login`, `gh auth login`, `az login`, `aws sso login`, an OAuth refresh) can be spawned by the app itself. The interactive part that genuinely needs the human is the browser SSO click, and only that. Copy-pasting the command is friction the software must absorb.

This is the same principle as the house rule for agents doing interactive auth (the agent runs the auth command; the human clicks SSO in the browser) — extended to the software the agents build. A worked one-click Salesforce reauth banner is in `reference.md`.

## The principle

On detecting an expired or invalid session:

1. **First move: launch the interactive reauth flow yourself** — spawn the login CLI (or kick the OAuth refresh) from the backend, in the background, and return immediately.
2. **The human's only step is the browser click-through.** The OAuth callback runs over a local HTTP server, not stdin — the spawned flow completes without any terminal interaction.
3. **Never print the command as the primary remedy.** The raw CLI invocation survives only as a fallback, for when the launched flow fails or the environment is headless.

If the app can detect `auth_expired`, it can also run the fix. Detection without programmatic remediation is half a feature.

## The UX contract

When auth is down, the UI owes the user all six of these:

- **Persistent banner, not a toast.** Auth-down is a state, not an event. The indicator stays visible until the session is restored — it must not auto-dismiss.
- **A primary one-click "Log in" action.** The button calls the backend (e.g. `POST /api/auth/login`); the backend spawns the login flow. No terminal, no copy-paste.
- **A visible pending state while the browser flow is open.** e.g. "Complete the SSO login in the browser window that just opened." The user must be able to tell that clicking worked.
- **Automatic success detection.** Poll a status probe (or subscribe) until the session verdict flips. Never ask the user "did it work?" — the app can check.
- **Auto-resume on success.** Clear the banner, then re-run whatever the expired session blocked (re-sync, retry the failed request). Success should feel like the interruption never happened.
- **The raw command as fallback only.** Keep it visible in small print (plus a "Retry" for sessions fixed outside the app), never as the primary path.

## Implementation guardrails

Check every one:

- **Single-flight.** A double-click (or two tabs) must not stack browser windows. Guard the launch with an in-progress flag/lock; while a flow is pending, subsequent launch requests return "already in progress" instead of spawning again.
- **Generous time bound — minutes, not the normal CLI timeout.** The flow includes a human clicking through SSO (possibly MFA). Bound it at something like 300s, not the 10–30s you'd give a non-interactive subprocess. But DO bound it: an abandoned browser window must not pin the in-progress flag forever.
- **Success must flip any TTL-cached auth verdict immediately.** If the app caches "auth ok/expired" with a TTL, a successful login must overwrite that cache on the spot. Otherwise the banner lingers until the TTL expires and the fix looks broken.
- **Failure surfaces the real reason.** Capture the login subprocess's stderr/exit and put the actual message in the error state (e.g. `login_error` on the status endpoint) — not a generic "login failed."
- **Schedulers never auto-launch browsers.** Background jobs, cron syncs, and retry loops that hit `auth_expired` set the state and stop. Popping a browser window with nobody at the keyboard is hostile; one-click stays user-initiated.
- **Treat the launch endpoint like any other process-spawning route.** Same CSRF/origin guards, no user-controlled arguments into the spawned command; keep the login target configurable via env (e.g. `SF_INSTANCE_URL`) rather than request input.

## Error-envelope shape

Whatever the transport, the auth-state surface needs three fields:

```json
{
  "auth_ok": false,
  "login_in_progress": true,
  "login_error": null
}
```

- `auth_ok` (or an `auth_expired` error code on failing responses) — drives the banner.
- `login_in_progress` — drives the pending state; also the single-flight signal.
- `login_error` — the real failure reason from the last attempted flow, cleared on the next launch.

The UI loop: banner on `auth_ok: false` → click → `login_in_progress: true` (pending copy) → poll → `auth_ok: true` (clear + resume) or `login_error` set (show it, keep the fallback command visible).

## When it applies

Any app, agent, service, or TUI that wraps a CLI or OAuth session that expires:

- Local or single-user web apps wrapping vendor CLIs.
- Services holding OAuth tokens where refresh can require re-consent.
- Desktop/Raycast/TUI tools shelling out to `gcloud`/`databricks`/`gh`/`az`/`aws`.
- Anywhere you're writing detection logic, an error envelope, or UI around an `auth_expired`-style state — if you're adding the detection, add the one-click fix in the same change.

**Not for:**

- **The agent's own auth during a session.** Run the login yourself and let the human complete browser SSO. When the human uses Omnigent from a phone or another device, use [mobile-sso](../mobile-sso/SKILL.md) for the clickable link and localhost callback handoff.
- **Multi-user server-side auth** where "reauth" means redirecting the requesting user through the app's own OAuth dance — standard web-auth patterns already cover that; this skill targets the wrapped-CLI/local-session shape.
- **Fully headless environments** with no browser and no human — there, fail fast with the exact command and where to run it.

→ Concrete endpoint, status, banner, and test walkthrough: `reference.md`.
