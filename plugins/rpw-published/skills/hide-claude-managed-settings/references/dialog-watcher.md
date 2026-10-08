# `claude-home`'s unattended-dialog watcher — decision rules and the regressions behind them

Read this before changing `assets/claude-home`'s `dismiss_decision`, `dismiss_log`, or
`dismiss_watch_loop`. Every rule here was paid for by a wedged wave or a keystroke typed into
a working session. Tests: `tests/test_claude_home_dialog_watcher.py`.

## Why it is a supervisor loop and not a startup one-shot (#1794)

The first version ran for **60 seconds**, `exit 0`ed after its first press, and matched the
literal string `Settings Error`. Wave 2026-09-13 then lost **three more workers at minute 10
each**, after ten had succeeded: the enterprise policy vetoes
`--permission-mode bypassPermissions`, so a tool-permission prompt (`Claude wants to call
**Bash**`) fires mid-session — by which time the watcher had long exited, and which says
nothing about settings anyway.

Three properties fix that class rather than that instance:

| Property | Why it is the fix |
|---|---|
| Lives as long as the launcher (`while kill -0 $launcher_pid`) | a prompt at minute 30 meets the same watcher as one at second 5 |
| Re-arms after every dismissal | one session can hit many prompts; the old loop answered one |
| Keyed on the **option affordance**, not a title | a numbered option list, a selection cursor on one of those rows, and a proceed-shaped option (`Continue without…`, `…ask again`, `Yes…`, `Allow…`, `Accept…`, `Proceed…`). A fourth dialog shape is covered the day it ships |
| A cursor-less candidate is **logged, never pressed** | ordinary agent output containing a numbered list gets no keystroke, and a real dialog that renders without a cursor becomes a log line instead of a silent miss |

## The decision rules

- **It presses the option it read, not a hardcoded digit.** `3` means "Continue without these
  settings" on the startup dialog and **"No, and tell Claude what to do differently"** on a
  permission prompt — a fixed digit would actively refuse the tool it was meant to allow. The
  scan prefers an option that also stops the dialog recurring (`don't ask again`).
- **It re-arms only once the dialog has left the pane.** Measured while building it: without
  that wait the loop re-presses into a pane that has not redrawn, the extra digits queue in the
  tty, and a *later* prompt gets answered by a stale keystroke. An un-cleared dialog after
  `CLAUDE_HOME_AUTO_DISMISS_GRACE` (15 s) is treated as a press that never landed, and pressed
  again.
- **Two options minimum, and a selection cursor** on one of the option rows, before anything is
  pressed. Two options plus a proceed-shaped one is not enough on its own: a worker writing
  *about* this watcher prints `1. Retry / 2. Continue without these settings` in its own output,
  and the watcher would type into a working session.
- **`ask again`, not `don't ask again`.** A typographic apostrophe is three bytes and awk's `.`
  is one, so matching the fuller phrase would silently demote the strongest option to a bare
  `Yes`.

## The cursor class is arrows only, and that is load-bearing (#1847)

It once included `>` and `*`, which are a markdown blockquote and a markdown bullet — so
`> 1. Retry` in a rendered diff, a `cat`ed notes file, or an agent's own prose about this
watcher *was* a cursor, and got a digit pressed into a working pane every `GRACE` seconds.

The claim that replaced it is narrower and true: every dialog Claude Code renders carries one
of `❯ ▶ ➤`, and **prose can carry a cursor**. Widening the class back is keystroke injection. A
test per forgeable character holds the line, plus a source-level assertion on the class itself.

## Only the cursor's own numbered block may answer (#1848)

Scoring used to accumulate across the whole capture with one global cursor flag, so a forged
`9.` anywhere in the pane decided which digit a *real* permission prompt received — a digit the
dialog does not have, which presses nothing and leaves the session wedged. The scan now resets
at each break in the numbered run and requires the winning key to come from the block that
supplied the cursor.

⚠️ **The wrapped-option trap.** Claude Code's grant option carries a full path, so in a narrow
pane its text wraps onto an indented second line. If a continuation line broke the numbered
block, the cursor and the grant option would land in different blocks and the watcher would
**report instead of press** — a wedge, which is worse than a misdirected digit. So an
**indented** non-option line continues the run; only a blank line or flush-left content ends
it. `test_a_wrapped_option_does_not_split_its_own_dialog` pins this.

## The dismissal log is operator-only and bounded (#1849)

`mkdir -p` at the default umask left `~/.claude-home/` 0755 and the log 0644, and `option=`
recorded pane text verbatim. The log now gets `umask 077` before the first append, a
`chmod 700`/`600` repair for a pair written before that fix, and an `option=` field truncated
to 80 characters — the audit value is which option *shape* was chosen, not a durable copy of
whatever was on the pane.
