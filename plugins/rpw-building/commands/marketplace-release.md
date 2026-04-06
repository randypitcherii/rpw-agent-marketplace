# /marketplace-release - Safe Marketplace Release Orchestrator

Run a consistent release flow for `rpw-agent-marketplace` with built-in guardrails.

Treat everything typed after `/marketplace-release` as optional context only; the command uses the repo `Makefile` flow.

## Intended Use

- Use after a production-ready change is merged locally and you need to bump marketplace versions.
- Keep release operations deterministic and aligned with `docs/release-log.md`.
- Avoid remote-dependent assumptions (works even when no git remote is configured).

## Safe Release Flow

1. Confirm current status:
   - Run `git status --short`.
   - Preserve unrelated local changes unless the user asks otherwise.
2. Preview bump impact:
   - Run `make marketplace-release-dry-run`.
3. Verify repository health:
   - Run `make verify` (or `make check` first if link/conversion validation is needed).
4. Satisfy public-release confirmation gate:
   - Set `PUBLIC_REPO_RELEASE_CONFIRM=I_ACKNOWLEDGE_PUBLIC_REPO_RELEASE`.
   - Run `make public-release-gate`.
5. Apply release bump + release log update:
   - Run `make marketplace-release`.
   - Optional: provide `PR_FIELD="<url-or-id>"` if you already have a PR reference.

## Release-Log Policy Notes

- New entries are inserted under `## Releases` at the top of `docs/release-log.md`.
- `PR` field defaults safely:
  - `Unavailable (no remote configured)` when no remote exists.
  - Current short commit ID when remotes exist (unless `PR_FIELD` override is provided).
- `Checks` defaults to `` `make verify` ✅ `` (override with `CHECKS_FIELD` if needed).
- Committed entries should have no placeholders or `TBD` values.

## Guardrails

- Never run destructive git commands.
- Never commit or push unless explicitly requested.
- If unexpected unrelated changes appear while releasing, stop and ask how to proceed.
- `make marketplace-release` will fail without explicit `PUBLIC_REPO_RELEASE_CONFIRM` acknowledgement.
