# Leak response — rotate first

If the content being scrubbed is a credential, the scrub is the *last* step and the least
important one. Work this list top to bottom.

## 1. Rotate, before touching git

Treat the credential as compromised from the moment it was committed. Rotation is the only action
that actually revokes access; everything else is cleanup.

- Issue a replacement credential.
- **Revoke or disable the old one** — a rotated-but-not-revoked key is still a live key.
- Verify the old credential now fails. An authentication attempt that returns 401/403 is the
  evidence; "we rotated it" is not.
- Update every consumer (secret manager, CI variables, deploy config, local `.env` files).

## 2. Assess the blast radius

- **How long was it exposed, and where?** Public repo, public mirror, or internal-only. Public
  means "harvested" — automated scanners find keys in public repos within minutes.
- **Did it ship anywhere else?** Published packages, container images, build artifacts, CI logs,
  error-tracking payloads, screenshots in issues or chat.
- **What could it reach?** Scope the permissions the credential had, not the ones it was used for.
- **Check for use.** Pull the provider's audit log for the exposure window and look for
  authentications you can't account for. This is the step that turns a scare into an incident, or
  closes it.

## 3. Report it

Follow whatever incident process the org has. A leaked production credential is usually a reportable
security event even if nothing was exploited — the decision about that is not the scrubber's to
make alone.

## 4. Then, optionally, scrub

Now the history rewrite is worth doing: it stops the value from spreading further and keeps it out
of future clones. It does not undo the exposure. Go back to `SKILL.md` and run the gate.

## What "scrubbed" does not mean

After a successful rewrite, these are still true:

- Anyone who cloned before the rewrite still has the secret.
- Forks and the GitHub fork network still resolve the old commits by SHA until GitHub GCs them.
- The value may already be in a third-party dataset, a search cache, or someone's scrollback.
- CI logs, artifacts, and any published package still contain it.

So the completion criterion for a leak is **"the credential is dead"**, never **"the commit is
gone"**. If you can only do one, rotate.

## Writing it up

Record: what was exposed, the exposure window, where it was reachable, what was rotated and when,
what the audit log showed, whether history was rewritten, and what guard was added to prevent a
recurrence. Never paste the credential itself into the write-up, the issue tracker, or the commit
message for the scrub.
