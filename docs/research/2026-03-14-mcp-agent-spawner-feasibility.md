# MCP Agent Spawner Feasibility Research

**Date**: 2026-03-14
**Question**: Can an MCP server enable nested agent spawning in Claude Code, deployable as a plugin?

---

## TL;DR

**Yes, it's technically feasible and already done by multiple projects.** The approach is proven: an MCP server shells out to `claude -p "prompt"` and returns the result. However, the cost-benefit is marginal for your use case given the flat dispatch model already works, subagent MCP tool access has known bugs, and each spawn burns ~50K tokens of overhead.

---

## 1. Technical Feasibility: Confirmed

### How It Works
An MCP server exposes a tool (e.g., `spawn_agent`) that runs `claude -p "prompt" --model sonnet --max-turns N` as a subprocess. The CLI executes, returns output to stdout, and the MCP server returns it as the tool result. The calling subagent receives the output as structured text.

### Authentication
Child `claude` processes inherit the parent's auth automatically. The CLI reads `~/.claude/` credentials. No extra auth configuration needed.

### Context / Repo Access
The spawned process runs in the same working directory and has full filesystem access. It reads the same CLAUDE.md, .mcp.json, etc. This means it also loads all MCP servers and plugins, contributing to the 50K token overhead.

### Key CLI Flags
- `-p "prompt"` — non-interactive one-shot mode
- `--model sonnet` — model selection
- `--max-turns N` — limit agent iterations (undocumented in `--help` but works)
- `--allowedTools "Bash(git:*)" "Write" "Read"` — restrict tool access
- `--output-format json` — structured output
- `--max-budget-usd N` — cost guardrail

### Latency
Each spawn incurs:
- Process startup: ~2-5 seconds
- System prompt injection: ~50K tokens loaded before any work
- No shared context with parent — everything must be in the prompt

---

## 2. Existing Solutions (3 Major Projects)

### steipete/claude-code-mcp
- **Stars**: High adoption, well-known
- **Architecture**: TypeScript MCP server, single `claude_code` tool
- **Mechanism**: Shells out to `claude` CLI with `--dangerously-skip-permissions`
- **Transport**: stdio
- **URL**: https://github.com/steipete/claude-code-mcp

### grahama1970/claude-code-mcp-enhanced
- **Architecture**: Enhanced version with "boomerang pattern" — task orchestration where parent breaks work into subtasks delegated to spawned agents
- **Features**: Parent-child task tracking, task automation from markdown lists
- **URL**: https://github.com/grahama1970/claude-code-mcp-enhanced

### BeehiveInnovations/pal-mcp-server
- **Architecture**: Provider Abstraction Layer — spawns not just Claude but also Codex CLI, Gemini CLI, etc.
- **Key Tool**: "clink" for spawning isolated subagents across different AI providers
- **Feature**: Returns only final results, preserving parent context window
- **URL**: https://github.com/BeehiveInnovations/pal-mcp-server

---

## 3. Critical Blocker: Subagent MCP Tool Access Is Buggy

Multiple open GitHub issues document that **subagents cannot reliably access MCP tools**:

| Issue | Problem |
|-------|---------|
| [#13605](https://github.com/anthropics/claude-code/issues/13605) | Custom plugin subagents cannot access MCP tools |
| [#13898](https://github.com/anthropics/claude-code/issues/13898) | Subagents hallucinate instead of calling project-scoped MCP servers |
| [#14496](https://github.com/anthropics/claude-code/issues/14496) | Task tool subagents fail to access MCP tools with complex prompts |
| [#13254](https://github.com/anthropics/claude-code/issues/13254) | Background subagents cannot access MCP tools |
| [#6915](https://github.com/anthropics/claude-code/issues/6915) | Feature request to scope MCP tools to subagents only |
| [#16177](https://github.com/anthropics/claude-code/issues/16177) | Feature request to enable specific MCP servers for subagents |

**This is the showstopper.** If subagents can't reliably call MCP tools, they can't call our spawner MCP server either. The existing projects (steipete, etc.) are designed for use from **Claude Desktop** or the **main agent**, not from subagents.

---

## 4. The Bash Tool Alternative

### How It Works
Subagents DO have the Bash tool. A subagent could directly run:
```bash
claude -p "do the thing" --model sonnet --max-turns 5 --output-format json 2>/dev/null
```

### Advantages Over MCP Server
- No MCP server to build or maintain
- No dependency on buggy subagent MCP tool access
- Works today with zero infrastructure
- Simpler error handling (just check exit code)

### Disadvantages
- No structured interface — raw stdout parsing
- No timeout management beyond bash timeout
- Each spawned agent loads full system prompt (~50K tokens)
- No visibility into nested execution from parent
- `--dangerously-skip-permissions` may be needed for non-interactive use, which is a security concern

### Verdict
The Bash tool workaround is the **pragmatic choice** if you need depth=2 spawning today. It sidesteps the MCP tool access bugs entirely.

---

## 5. Cost-Benefit Analysis

### Build Cost (MCP Server)
- **Effort**: ~4-8 hours for a minimal Python MCP server that shells out to `claude -p`
- **Maintenance**: Low if simple, high if you add orchestration features
- **Plugin packaging**: Straightforward — stdio server in plugin directory

### Token Overhead Per Spawn
- ~50K tokens for system prompt + tool catalog + CLAUDE.md + plugin skills
- Multiplied by every spawn: N turns x M subprocesses
- With `--allowedTools` filtering, can reduce but not eliminate

### Failure Modes
1. **Orphaned processes**: Spawned `claude` processes that don't terminate
2. **Token runaway**: No shared budget — each subprocess has independent token counting
3. **Rate limiting**: Multiple concurrent spawns hit API rate limits
4. **Context loss**: Each spawn starts fresh, no memory of parent conversation
5. **Recursive spawning**: Without depth guards, agents could spawn agents indefinitely

### General-Purpose Plugin Potential
Yes, this could be useful to others. steipete's version has significant adoption. But the existing solutions already cover this — building another would be duplicative.

---

## 6. Recommendation

**Don't build this.** Here's why:

1. **The MCP access bug blocks the primary use case.** Subagents can't reliably call MCP tools (issues #13605, #13898, #14496). Until Anthropic fixes this, an MCP spawner called from a subagent is unreliable.

2. **The Bash workaround already works.** If you genuinely need depth=2, have the subagent run `claude -p` via Bash. No infrastructure needed.

3. **Existing solutions exist.** steipete/claude-code-mcp and pal-mcp-server already do this well. No need to rebuild.

4. **The flat dispatch model is better.** 50K tokens per spawn means depth=2 costs ~100K tokens before any work happens. The flat model where the orchestrator directly dispatches all tasks is more token-efficient and easier to debug.

5. **Anthropic is actively working on this.** Multiple feature requests (#6915, #16177, #23374) suggest official support for subagent MCP access is coming. Wait for the platform to catch up.

### If You Still Want To Experiment
The simplest path: add a one-liner to your dispatch skill instructions telling subagents they can use `claude -p` via Bash for delegation. No MCP server, no plugin, no maintenance.

---

## Sources

- [Claude Code Subagent Docs](https://code.claude.com/docs/en/sub-agents)
- [Claude Code CLI Reference](https://code.claude.com/docs/en/cli-reference)
- [steipete/claude-code-mcp](https://github.com/steipete/claude-code-mcp)
- [grahama1970/claude-code-mcp-enhanced](https://github.com/grahama1970/claude-code-mcp-enhanced)
- [BeehiveInnovations/pal-mcp-server](https://github.com/BeehiveInnovations/pal-mcp-server)
- [50K Token Overhead Analysis](https://dev.to/jungjaehoon/why-claude-code-subagents-waste-50k-tokens-per-turn-and-how-to-fix-it-41ma)
- [Issue #4182 - Nested Agent Limitation](https://github.com/anthropics/claude-code/issues/4182)
- [Issue #13605 - Plugin Subagents Can't Access MCP](https://github.com/anthropics/claude-code/issues/13605)
- [Issue #13898 - Subagents Hallucinate MCP Results](https://github.com/anthropics/claude-code/issues/13898)
- [Issue #14496 - MCP Fails With Complex Prompts](https://github.com/anthropics/claude-code/issues/14496)
- [Issue #13254 - Background Subagents Can't Access MCP](https://github.com/anthropics/claude-code/issues/13254)
- [dangerously-skip-permissions Security Risks](https://thomas-wiegold.com/blog/claude-code-dangerously-skip-permissions/)
