# Lens briefs

Send each lens the **common preamble** followed by its **lens block**. Fill in `<REPO>`, the per-lens hints you found while orienting (the big, quiet areas and declared-frozen subsystems), and a tool-call budget.

## Common preamble

```text
READ-ONLY review task. Repo: <REPO> (cd there; do NOT edit, commit, branch, or file issues).
Read the repo's agent guide / README first, then nested guides only for areas you dig into.

Goal: find parts of this repo that should be REMOVED or SIMPLIFIED. Every finding must carry
hard evidence: a grep showing zero callers, a git-log last-touch date, the duplicate file
pair (hashes), the decision record that froze or superseded it. No vibes.

Before calling anything dead, check INDIRECT references: build files (Makefile, justfile,
package.json scripts), CI workflows, service definitions (launchd/systemd/cron), plugin or
package manifests, docs and skill bodies that tell a HUMAN to run it, tests, eval fixtures
and datasets that name paths as text, and string-built paths. Never truncate a zero-caller
grep with `head`.

Return ONLY:
1. A markdown table, max 12 rows, ranked by payoff x confidence:
   | # | Path(s) | Action (remove/merge/simplify/shrink) | Evidence | Est. lines saved | Confidence H/M/L | Risk / what breaks |
2. "Rejected candidates": max 6 bullets, each a thing that LOOKED dead but is not, and why.
3. "Decisions needed": anything governed by a decision record or an open issue, one line each.
Budget: ~<N> tool calls.
```

## Lens blocks

**Dead code & orphans**
```text
YOUR LENS: DEAD CODE & ORPHANS. Hunt: scripts with no caller; build targets nobody invokes
from CI, docs, or other targets; modules/functions with no importers; tests that test
removed features; services/automation no longer installed; stale config and fixture files;
thin wrapper layers (e.g. a task-runner file that only delegates to another).
```

**Frozen & superseded**
```text
YOUR LENS: FROZEN, DEPRECATED & SUPERSEDED. Start from the decision records. For every
subsystem declared frozen/deprecated: measure exactly what still imports it (an import
closure from the live consumers, not a guess) and what could go. Also: decision records
marked superseded whose code still exists, deprecated CLI subcommands and build targets,
migration shims and compatibility aliases past their stated removal date, always-on flags,
and grep hits for deprecated/legacy/TODO remove/"remove once".
```

**Duplication & over-abstraction**
```text
YOUR LENS: DUPLICATION & OVER-ABSTRACTION. Hunt: byte-identical or near-identical files
(hash them, diff same-named files); several implementations of one concern (auth, config,
ports, clients, logging, browser drivers) that bypass the shared library; abstractions with
one implementation; files over ~1500 lines that should split along existing section
boundaries; sub-projects carried in-tree but excluded from the build/test gate.
Deliberate copies (vendored with a sync check, generated mirrors, bundles that must be
self-contained) belong under Rejected unless the reason behind them is gone.
```

**Docs, skills & process sprawl**
```text
YOUR LENS: DOCS, SKILLS & PROCESS SPRAWL. Hunt: docs with zero inbound links; docs whose
backticked/linked repo paths no longer resolve; process docs that restate a skill or the
agent guide; agent-guide files over their stated length budget (they load every session);
logs and changelogs nobody has appended to in months; archive directories git history
already preserves; overlapping skills/commands/agents (compare descriptions and triggers);
CI workflows that are disabled or duplicate one another; large committed binaries.
```
