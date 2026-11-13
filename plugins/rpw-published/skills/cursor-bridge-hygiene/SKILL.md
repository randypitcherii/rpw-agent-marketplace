---
name: cursor-bridge-hygiene
description: Explain the `.cursor/mcp.json` and `.cursor/hooks.json` files an Omnigent Cursor session writes into a worktree — who writes them, why they land in-tree, and why they must never be committed. Use when a Cursor session leaves `?? .cursor/` in `git status`, or before adding a `.cursor` ignore rule or writer to this repo.
---

# Cursor bridge hygiene

An Omnigent Cursor session can leave `.cursor/mcp.json` and `.cursor/hooks.json` in the worktree it opened. Both files have machine-local absolute paths and a per-session bridge dir baked in. **Never commit them.**

Nothing in this repo writes those files. The writer is the **upstream** Omnigent Cursor-native bridge, so a fix inside this repo can only hide the symptom.

Before you change anything here, read [references/bridge-hygiene.md](references/bridge-hygiene.md). It covers:
- the exact upstream writers
- the ephemeral bridge dir the files should live in
- why the Cursor CLI forces them in-tree today
- why an ignore rule is a suppression, not the fix

Live check: `uv run pytest tests/test_cursor_bridge_hygiene.py -q`. It has a canary over the real upstream writer that goes red the day upstream fixes it. Tracking issue: #1128.

Cursor needs no command-linking setup. Omnigent runs Cursor sessions with the plugin's skills and commands, and #2364 deleted the old `make link-cursor` path.
