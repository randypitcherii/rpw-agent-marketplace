# Parallel Build Swarm Research

**Date:** 2026-03-10
**Status:** Research complete, ready for implementation

## Executive Summary

There are three distinct parallelism mechanisms available in Claude Code, each suited to different layers of the `/build` command. The current `/build` already uses **subagent worktrees** (mechanism 1). The new **Agent Teams** feature (mechanism 2) and **manual parallel sessions** (mechanism 3) unlock fully independent `/build` sessions running concurrently.

---

## Three Parallelism Mechanisms

### 1. Subagent Worktrees (Current — Within a Single /build)

**What we have today.** The `/build` orchestrator dispatches up to 5 `impl-{bead-id}` subagents via the Agent tool with `isolation: "worktree"` and `run_in_background: true`. Each gets its own worktree branching from the build's feature branch.

- **Strengths:** Fully automated, squash-merge fan-in, no human coordination needed.
- **Limits:** All subagents share one parent session's context window and API rate limit. Max 5 concurrent implementers. One level of nesting (depth 2 max per feasibility research).
- **No changes needed** — this layer works well already.

### 2. Agent Teams (New — Experimental Feature)

**Separate Claude Code instances** coordinated by a team lead via shared task list and mailbox.

**How to enable:**
```json
// settings.json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

**Architecture:**
| Component | Role |
|-----------|------|
| Team lead | Main session that creates team, assigns tasks, synthesizes results |
| Teammates | Independent Claude Code instances with their own context windows |
| Task list | Shared work items stored at `~/.claude/tasks/{team-name}/` |
| Mailbox | Inter-agent messaging system |

**Key properties:**
- Each teammate is a **full independent Claude Code session** with its own context window.
- Teammates inherit the lead's permission settings at spawn time.
- Task dependencies are managed automatically — blocked tasks unblock when dependencies complete.
- Task claiming uses file locking to prevent race conditions.
- Display modes: **in-process** (Shift+Down to cycle) or **split-pane** (tmux-based, click into panes).
- You can message teammates directly, redirect their approach, or shut them down individually.
- **Known limitations:** Experimental. Issues around session resumption, task coordination edge cases, and shutdown behavior.

**Best use cases for agent teams:**
- Research and review (multiple perspectives simultaneously)
- Competing hypotheses investigation
- Parallel code review
- Multi-feature development where features are independent

### 3. Manual Parallel Sessions (Git Worktrees)

**Fully manual** — you open multiple terminal tabs, each running `claude --worktree <name>`.

```bash
# Terminal 1
claude --worktree feature-auth

# Terminal 2
claude --worktree bugfix-123

# Terminal 3
claude --worktree refactor-api
```

- Worktrees created at `<repo>/.claude/worktrees/<name>`, branch named `worktree-<name>`.
- Each session is completely independent — no coordination, no shared task list.
- On exit: no-change worktrees auto-cleaned; changed worktrees prompt to keep/remove.

---

## Proposed Architecture: Build Swarm

A **meta-orchestrator** that coordinates multiple independent `/build` sessions, each running in its own worktree with full autonomy.

### Layer Diagram

```
┌─────────────────────────────────────────────┐
│           Meta-Orchestrator (Human or Lead)  │
│  - Decomposes epic into independent features │
│  - Assigns each feature to a build session   │
│  - Monitors progress, resolves conflicts     │
└──────┬──────────┬──────────┬────────────────┘
       │          │          │
  ┌────▼───┐ ┌───▼────┐ ┌───▼────┐
  │/build A│ │/build B│ │/build C│   ← Independent sessions
  │worktree│ │worktree│ │worktree│     (agent team teammates
  │ + subs │ │ + subs │ │ + subs │      OR manual sessions)
  └────┬───┘ └───┬────┘ └───┬────┘
       │         │          │         ← Each /build has its own
    impl-1    impl-1     impl-1        subagent fan-out (up to 5)
    impl-2    impl-2     impl-2
```

### Option A: Agent Teams as Swarm Backbone (Recommended)

Use the new agent teams feature where the lead session acts as meta-orchestrator:

```
Prompt to lead:
"Create an agent team with 3 teammates. Each teammate should run /build
for one of these features:
  1. Teammate 'auth': /build implement OAuth2 flow
  2. Teammate 'api': /build add pagination to REST endpoints
  3. Teammate 'ui': /build redesign settings page

Each teammate works in its own worktree. Coordinate via the task list.
I'll review PRs as they come in."
```

**Advantages:**
- Built-in task list with dependency tracking
- Mailbox for inter-agent communication
- Lead can monitor, redirect, and synthesize
- Each teammate gets its own context window (no context sharing bottleneck)

**Disadvantages:**
- Experimental, known limitations around shutdown/resumption
- Each teammate's `/build` spawns its own subagents → could be 3 builds x 5 subs = 15 concurrent agents
- API rate limits become the binding constraint

### Option B: Manual Parallel Sessions

Open N terminal tabs, each with `claude --worktree <feature-name>`, run `/build` in each.

**Advantages:**
- Simpler, no experimental features needed
- Full human control over each session
- Can use different models per session

**Disadvantages:**
- No automated coordination
- Human must manually resolve merge conflicts
- Human must track which sessions are doing what

### Option C: Headless Parallel Builds (CI/CD Style)

Use `claude --headless` programmatically to launch builds:

```bash
# Launch parallel builds via headless mode
claude --worktree feat-auth --headless -p "/build implement OAuth2" &
claude --worktree feat-api --headless -p "/build add pagination" &
claude --worktree feat-ui --headless -p "/build redesign settings" &
wait
```

**Advantages:**
- Scriptable, can integrate with CI
- No interactive session needed
- Can be wrapped in a Makefile target

**Disadvantages:**
- No mid-flight human intervention
- Must handle permission prompts upfront (`--dangerously-skip-permissions` or pre-approved allowlists)

---

## Conflict Avoidance Strategy

### Rule 1: Feature-Level Isolation
Each `/build` session works on a completely independent feature with its own branch. Features must not overlap in files touched.

### Rule 2: Worktree Isolation (Mandatory)
Every build session and every subagent within it operates in its own git worktree. No two agents share a working directory.

### Rule 3: Squash-Merge Fan-In
- Subagents squash-merge into their parent build's feature branch.
- Each build's feature branch creates its own PR to the default branch.
- PRs are merged sequentially (GitHub handles conflict detection).

### Rule 4: File-Level Separation at Planning Time
The meta-orchestrator (or human) must ensure that independent builds do not modify the same files. If overlap is unavoidable:
- Serialize those builds (one waits for the other)
- Or assign the overlapping files to one build and have the other depend on it

### Rule 5: Shared Files Protocol
For files that many features touch (e.g., `package.json`, `CHANGELOG.md`, route registrations):
- Defer shared-file updates to a final integration step
- Or assign one build as the "anchor" that owns shared files; others rebase after it merges

---

## Resource Management

### API Rate Limits (Primary Constraint)
- Each Claude Code session consumes API tokens independently.
- With agent teams: lead + N teammates, each potentially spawning up to 5 subagents.
- **Recommendation:** Cap at 3 concurrent `/build` sessions, each with max 3 subagents = 12 total agents (including leads).
- Monitor for 429/rate-limit errors; back off by reducing subagent fan-out first.

### CPU and Memory
- Each Claude Code session is a Node.js process (~200-400MB RAM).
- Each worktree is a full working copy (shared `.git` via symlinks, but separate working files).
- **Recommendation:** For 3 parallel builds: expect ~2-4GB RAM for Claude Code processes + worktree disk space.
- On macOS with 32GB+ RAM, this is comfortable. On 16GB, limit to 2 parallel builds.

### Context Window
- Agent teams solve the context window problem: each teammate has its own independent context.
- Subagents within a build also have independent contexts.
- The team lead's context is the bottleneck for coordination — keep coordination prompts concise.

### Token Cost
- N parallel builds consume roughly N times the tokens of a single build.
- Subagent fan-out multiplies further: 3 builds x 5 subs x ~100K tokens each = ~1.5M tokens.
- Use Haiku-model agents for lightweight tasks (bead admin, simple reviews) to reduce cost.

---

## Implementation Recommendations

### Immediate (No Code Changes)

1. **Enable agent teams** in settings.json:
   ```json
   {"env": {"CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"}}
   ```

2. **Try manual parallel builds** by opening 2-3 terminals with `claude --worktree <name>` and running `/build` in each. This validates the workflow before automating.

3. **Reduce subagent fan-out** when running parallel builds: lower the max from 5 to 3 per build to stay within rate limits.

### Short-Term (Plugin Changes)

4. **Create the three missing superpowers** that are referenced but don't exist:
   - `superpowers/dispatching-parallel-agents.md`
   - `superpowers/subagent-driven-development.md`
   - `superpowers/using-git-worktrees.md`

5. **Add a `/build-swarm` command** (or `--swarm` flag to `/build`) that:
   - Accepts an epic description with multiple features
   - Decomposes into independent feature builds
   - Validates no file-level overlap between features
   - Launches each as an agent team teammate or headless session
   - Collects results and creates a summary PR or per-feature PRs

6. **Add a `make parallel-build` target** that wraps headless parallel builds:
   ```makefile
   parallel-build:
   	@echo "Launching parallel builds..."
   	claude --worktree feat-1 --headless -p "/build $(FEAT1)" &
   	claude --worktree feat-2 --headless -p "/build $(FEAT2)" &
   	wait
   ```

### Medium-Term (Architecture)

7. **Build a coordination layer** that:
   - Maintains a build registry (which features are in-flight, their branches, their status)
   - Detects file-level conflicts before dispatching
   - Sequences shared-file updates
   - Provides a dashboard view of all active builds

8. **Integrate with Beads** for cross-build traceability:
   - Epic bead → feature beads → sub-beads per build
   - Cross-build dependency tracking

---

## Key Sources

- Claude Code Agent Teams docs: https://docs.anthropic.com/en/docs/claude-code/agent-teams
- Claude Code Sub-agents docs: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Claude Code Common Workflows (worktrees): https://docs.anthropic.com/en/docs/claude-code/common-workflows
- Project feasibility research: `docs/research/2026-03-08-subagent-created-subagent-feasibility.md`
- Current build command: `plugins/rpw-building/commands/build.md`
- Current subagent dispatch: `plugins/rpw-building/skills/subagent-dispatch.md`
