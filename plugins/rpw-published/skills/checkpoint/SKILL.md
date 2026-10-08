---
name: checkpoint
description: Dump the current session to disk from its transcript .jsonl, spending zero tokens on the conversation. Use when checkpointing before a context compaction or handoff, when asked to "checkpoint", "save the session", "write down where we are", or "dump the transcript", and at the end of a long session whose detail should outlive it. This only RECORDS — for an interpreted summary use where-were-we or session-report:report instead.
---

# Checkpoint

Write the session to disk **without reading it.** The full record is already on disk in the session `.jsonl`; a script renders it. Do not summarize, do not open the transcript, do not read the output files.

## Do this

```bash
uv run --no-project python \
  "$CLAUDE_PLUGIN_ROOT/skills/checkpoint/scripts/render_checkpoint.py"
```

Run it from the project directory you are working in. It finds the live session itself (newest `.jsonl` under `~/.claude/projects/<cwd with / as ->`), writes both files, and prints their paths.

Then **print the two paths it printed and stop.** That is the whole skill.

## What it wrote

```
.session-state/checkpoints/
  <stamp>--checkpoint--INDEX.md        <- read this
  <stamp>--checkpoint--TRANSCRIPT.md   <- grep this, never read whole
```

- **INDEX** — machine-gathered header (session id, cwd, branch, HEAD, dirty paths, time span, turn counts) plus the de-noised spine: every user prompt, assistant prose, and one line per tool call with a short arg hint and ✅/❌. Tool results, file contents, command output, diffs, and thinking are excluded, so it stays readable in full.
- **TRANSCRIPT** — the full mechanical render including results and subagent (sidechain) turns. Anchors `[#NNNN]` match the INDEX: grep one out, never load the file.

`.session-state/` is gitignored, so checkpoints stay out of diffs and the secret-scan gate.

## Options (rarely needed)

| Flag | Use |
|---|---|
| `--session-file <path>` | Render a specific `.jsonl` instead of the newest one — e.g. a session that has since ended. |
| `--cwd <dir>` | Project dir to resolve the session from and write under, when you are not standing in it. |
| `--out-dir <dir>` | Write the pair somewhere other than `<cwd>/.session-state/checkpoints`. |

## Reading a checkpoint later

Open the **INDEX** only. It says what the session did and what was left unfinished. When a line shows *that* something happened and you need the detail, `grep -n '#0042' <...>--TRANSCRIPT.md` with context — reading the transcript whole spends exactly the tokens this skill exists to save.
