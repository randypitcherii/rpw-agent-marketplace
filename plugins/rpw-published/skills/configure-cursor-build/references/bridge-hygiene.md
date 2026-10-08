# Cursor bridge hygiene — why `.cursor/` appears in a worktree

Read this when a Cursor session leaves `?? .cursor/` in `git status`, when
deciding whether that path may be committed, or before "fixing" it in this repo.

## The one-line answer

**No file in this repo writes it.** `.cursor/mcp.json` and `.cursor/hooks.json`
are written by the **upstream Omnigent Cursor-native bridge**, into whatever
workspace the session opens. The fix belongs upstream in
`omnigent-ai/omnigent`; nothing in `rpw-agent-marketplace` can move those files.

## Who writes what, exactly

Verified against `omnigent 0.14.0.dev0 (860666e0)`:

| File written | Upstream writer | Line |
|---|---|---|
| `<workspace>/.cursor/mcp.json` | `omnigent.harnesses.cursor_native.bridge.write_mcp_config` | `bridge.py:341` (`cursor_dir = workspace / ".cursor"`) |
| `<workspace>/.cursor/hooks.json` | `omnigent.harnesses.cursor_native.bridge.write_hooks_config` | `bridge.py:437` (same expression) |
| Both call sites | `omnigent.runner.native.orchestration` | `orchestration.py:2635,2638` — `write_*_config(Path(workspace), bridge_dir)` |

Both writers **merge** rather than clobber, so a repo that intentionally
versions project-level Cursor config keeps its entries — and gets Omnigent's
machine-local ones added alongside.

## The ephemeral location already exists

`bridge.py:112` — `bridge_dir_for_session_id()` returns
`$TMPDIR/omnigent-<uid>/cursor-native/<sha256(session_id)[:32]>`. Per-session
bridge state (`cursor_usage.jsonl`, the relay MCP config) already lives there.
The `.cursor/` writes are the **only** part of the Cursor bridge that lands in
the working tree.

So the destination is not the open question. The open question is how Cursor
finds config that is not in the workspace.

## Why it lands in-tree: Cursor CLI has no config-root flag

`cursor-agent --help` (checked) exposes `--workspace`, `--add-dir`,
`--plugin-dir`, `--worktree` — and **nothing** that relocates project-scoped
config discovery. `mcp.json` / `hooks.json` are found at `<workspace>/.cursor/`
or not at all, so the bridge writes them where the TUI will read them.

**The upstream fix shape already exists in the same codebase.** The
`opencode_native` bridge redirects its harness's config discovery instead of
writing into the workspace — `orchestration.py:1290` calls
`xdg_config_home_for_bridge_dir(bridge_dir)` and hands the harness a
bridge-dir-rooted config home. A `HOME`/config-root redirect for `cursor-native`
(or a teardown that removes exactly the Omnigent entries plus any `.cursor/` the
bridge created) is the same move.

## The live check

Reproduce it against the real writer, hermetically — no live worktree touched,
no `HOME` mutation (`write_hooks_config` never touches the bridge dir on disk):

```sh
uv run pytest tests/test_cursor_bridge_hygiene.py -q
```

`test_real_bridge_writer_still_dirties_a_clean_worktree` is a **canary**: it
asserts today's known-bad behavior. When it starts FAILING, upstream shipped the
fix and issue #1128 can close. It is skipped when `omnigent` is not importable.

That canary is the only automated signal available here. It proves what the
writer does to a scratch repo; it does **not** prove a full interactive
`omnigent cursor` session start/stop leaves nothing behind, because that needs a
live host, a tmux pane and a Cursor login.

## What NOT to do

- 🚫 **Do not treat `.gitignore` as the fix.** This repo already ignores
  `.cursor/` (`.gitignore:42`, added by PR #1192). That suppresses the dirty
  `git status` this repo sees; it does not move the files, and the stale
  absolute `--bridge-dir` path still outlives the worktree that held it.
- 🚫 **Do not add a cleanup sweep over existing worktrees.** There are ~70 on
  this machine, several belonging to running sessions.
- ✅ **Do route the real fix upstream** via the `omnigent-contribution` skill —
  the same path issue #1002 uses for a native-bridge defect.

## Contents of the generated files

Both bake machine-local absolute paths, which is why they must never be
committed:

```json
{"hooks": {"stop": [{"command":
  "/…/uv/tools/omnigent/bin/python -I -m omnigent.harnesses.cursor_native.usage \
   record-usage --bridge-dir /…/T/omnigent-502/cursor-native/<session-hash>"}]},
 "version": 1}
```
