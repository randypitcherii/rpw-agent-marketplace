---
name: rpw-published-where-were-we
description: Re-run session orientation — shows current git state, GitHub Issues status, project files, and suggests the next best activity.
---

# /where-were-we - Session Orientation

Run this to re-display the session orientation report at any time.

## Execution

Run the orientation hook inline via Bash. `RPW_ORIENT=1` forces it to run —
this is an explicit user invocation, so it bypasses the opt-in gate that keeps
the SessionStart hook silent by default:

```bash
RPW_ORIENT=1 CLAUDE_PLUGIN_ROOT=plugins/rpw-published bash plugins/rpw-published/hooks/session-start-orient.sh
```

Present the output to the user as a concise summary of where things stand. If the report identifies in-flight or ready work, ask what they'd like to pick up next.

## Scope and Safety

- Read-only. Do not modify files, create commits, or change issue state.
