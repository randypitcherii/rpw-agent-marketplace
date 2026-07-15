---
name: configure-cursor-build
description: Configure Cursor with the /build command from rpw-published. Use when setting up Cursor to use the build workflow, or when the user asks to add/configure the build command in Cursor.
---

# Configure Cursor with /build

Helps configure Cursor so the `/build` command is available. The build command lives in `plugins/rpw-published/commands/` and provides the full lifecycle development orchestrator workflow.

## Build Pattern Behavior in Cursor

`build.md` supports two request patterns:

- `/build <request>` -> full planning workflow with explicit approvals.
- `/build without planning: <request>` (or `/build --without-planning <request>`) -> condensed planning + single go/no-go approval before implementation.

Cursor keeps a safety confirmation step even for "without planning" requests.

## Current State (Manual)

Cursor does not yet natively support the same plugin command hooks as Claude Code. Configuration requires manual steps.

### Steps for the Agent

1. **Locate the build command source**
   - Path: `plugins/rpw-published/commands/build.md` (unified command)
   - Or the repo root if working from a cloned marketplace

2. **Create or update Cursor commands**
   - Cursor commands dir: `~/.cursor/commands/`
   - Create a symlink or copy `build.md` so Cursor can find it
   - From the marketplace repo: `make link-cursor` links `build.md` into `~/.cursor/commands/`

3. **Verify**
   - Run `make check-links` to confirm the symlink status
   - User can test `/build` in Cursor

4. **If user has existing build from elsewhere**
   - Run `make unlink` first to remove old links
   - Then `make link-cursor`

### Commands Reference

| Command | Purpose |
|---------|---------|
| `make link-cursor` | Link build.md into ~/.cursor/commands |
| `make unlink` | Remove links from ~/.cursor/commands |
| `make check-links` | Verify symlink status |
| `make check` | Run project gate (alias for `make verify`) |
| `make adopt-cursor` | Backup existing files, then link |

## Future State

Ideally Cursor will directly support the same plugin/hook mechanism the build command uses. When that happens, this skill can be simplified to: "Install the rpw-published plugin; Cursor will load the build command automatically."

## Related

- **Claude**: Gets `/build` from the rpw-published plugin when the marketplace is installed. No symlink needed.
- **configure-cursor-build**: This skill — Cursor setup requires manual linking for now.
