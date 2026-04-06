---
name: rpw-building-where-were-we
description: Re-run session orientation — shows current git state, beads status, project files, and suggests the next best activity.
aliases:
  - now-what
  - next
---

# /where-were-we - Session Orientation

Run this to re-display the session orientation report at any time.

## Execution

Run the orientation hook inline via Bash:

```bash
CLAUDE_PLUGIN_ROOT=plugins/rpw-building bash plugins/rpw-building/hooks/session-start-orient.sh
```

Present the output to the user as a concise summary of where things stand. If the report identifies in-flight or ready work, ask what they'd like to pick up next.

## Scope and Safety

- Read-only. Do not modify files, create commits, or change bead state.
