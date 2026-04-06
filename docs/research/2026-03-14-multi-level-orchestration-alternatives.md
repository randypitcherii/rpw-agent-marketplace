# Multi-Level Agent Orchestration Alternatives

**Date:** 2026-03-14
**Context:** Claude Code hard-caps subagent depth at 1. Evaluating alternatives for patterns like Orchestrator -> Lead -> Worker.

---

## Executive Summary

**LangGraph is the only production-ready framework that natively supports arbitrary-depth nested agent hierarchies today.** The Claude Agent SDK is the closest to your existing ecosystem but also caps at depth=1. A hybrid approach (Claude Agent SDK for the outer orchestrator, calling Claude API directly for inner levels) is the most pragmatic path if you want to stay in the Anthropic ecosystem.

---

## Framework-by-Framework Analysis

### 1. Claude Agent SDK (Python/TypeScript)

- **Depth support:** Depth=1 only. Subagents cannot spawn subagents. The `Task` tool is explicitly excluded from subagent tool lists.
- **Agent Teams:** Also depth=1. Teammates lose Agent, TeamCreate, TeamDelete tools at spawn time. Hub-and-spoke enforced architecturally.
- **Integration with your plugins:** Excellent. Same tools, MCP servers, and context management as Claude Code. Python (`v0.1.48`) and TypeScript (`v0.2.71`) packages available.
- **Migration cost:** Near-zero for depth=1 workflows. For depth>1, you'd need to build a custom orchestration layer on top.
- **Production readiness:** Production-ready for depth=1. Agent Teams is research preview.
- **Workaround for depth>1:** Build a custom Python/TS orchestrator using the Agent SDK that manually manages the hierarchy. The outer orchestrator creates "lead" agents via the SDK, and those leads use raw Claude API calls (not the Agent tool) to coordinate workers. You control the depth yourself.

### 2. LangGraph (LangChain)

- **Depth support: YES, unlimited.** First-class `create_supervisor()` pattern where supervisors can manage other supervisors. Compile a team as a graph node, then nest it inside another supervisor.
- **Example pattern:**
  ```python
  research_team = create_supervisor([research_agent, math_agent], model=model).compile(name="research_team")
  writing_team = create_supervisor([writing_agent, publishing_agent], model=model).compile(name="writing_team")
  top_level = create_supervisor([research_team, writing_team], model=model).compile(name="top_level")
  ```
- **Integration with your plugins:** Poor. Completely different ecosystem. Your MCP servers, CLAUDE.md, skills, hooks — none transfer. You'd need to rewrite tool integrations as LangChain tools.
- **Migration cost:** High. Full rewrite of orchestration layer. Can still use Claude as the underlying LLM via LangChain's ChatAnthropic provider.
- **Production readiness:** Production-ready. `langgraph-supervisor` package on PyPI and npm. 40% enterprise adoption projected by 2026.
- **Tradeoffs:** Most capable for depth>1, but you lose the entire Claude Code development experience (interactive coding, file editing, bash, etc.).

### 3. Microsoft AutoGen (now Microsoft Agent Framework)

- **Depth support: YES, via nested teams.** Teams can be participants within outer teams. `SocietyOfMindAgent` wraps an inner team as a single participant in an outer team.
- **Architecture:** Actor model (v0.4+). Core layer handles message routing; AgentChat layer provides high-level team patterns (RoundRobinGroupChat, SelectorGroupChat, Swarm).
- **Integration with your plugins:** Poor. Different ecosystem entirely. Would need custom tool adapters.
- **Migration cost:** High. Different paradigm (actor model vs tool-based).
- **Production readiness:** Stable (v0.4+), but migrating to "Microsoft Agent Framework" branding. Some API churn risk.
- **Tradeoffs:** Most flexible architecture (actor model), but heavyweight and the ecosystem is in transition.

### 4. CrewAI

- **Depth support: Partial.** `Process.hierarchical` adds a manager agent that delegates to workers. `allowed_agents` parameter (Jan 2025) enables controlled delegation chains. But no true nested sub-crew composition — it's manager -> workers, not manager -> sub-manager -> workers.
- **Integration with your plugins:** Poor. Own ecosystem, own tool system.
- **Migration cost:** Medium. Simpler API than LangGraph/AutoGen, but still a full rewrite.
- **Production readiness:** Production-ready but community reports reliability issues with autonomous delegation.
- **Tradeoffs:** Easiest to learn of the non-Anthropic options, but the depth limitation makes it barely better than what you already have.

### 5. OpenAI Agents SDK (formerly Swarm)

- **Depth support: Technically yes, via handoff chains.** Agent A hands off to Agent B, who can hand off to Agent C. Also supports "agent as tool" pattern where a manager calls sub-agents as tools.
- **Nested handoffs:** Beta feature (`RunConfig.nest_handoff_history`). Collapses prior transcript into summary when handing off.
- **Integration with your plugins:** Poor. OpenAI-native. Different model provider entirely.
- **Migration cost:** High. Different LLM, different tool system, different everything.
- **Production readiness:** Beta for nested features. Core SDK is stable.
- **Tradeoffs:** Good design patterns to study, but switching to OpenAI models is a non-starter if you're invested in Claude.

### 6. Claude Code Hooks/MCP Workaround

- **Concept:** Build an MCP server that acts as an "agent spawner" tool. When a subagent needs to delegate, it calls the MCP tool instead of the Agent tool. The MCP server spawns a new Claude API call (or Claude Agent SDK session) externally.
- **Depth support: Unlimited in theory.** The MCP server manages its own process tree outside Claude Code's depth enforcement.
- **Integration with your plugins:** Excellent. It's an MCP server — fits natively into your plugin ecosystem. PreToolUse hooks can intercept and route. Subagents get `agent_id` and `agent_type` in hook context.
- **Migration cost:** Medium. Need to build the MCP server and the dispatch logic. But your existing plugins, CLAUDE.md, and skills all stay intact.
- **Production readiness:** Custom/experimental. You're building infrastructure.
- **Tradeoffs:** Most ecosystem-compatible workaround. Risk is complexity of managing the process tree, context passing, and error handling yourself. Also bypasses Anthropic's intentional safety guardrail.

### 7. Custom Orchestrator (Claude API Direct)

- **Concept:** Write a Python/TS orchestrator that uses the Claude API (Messages API with tool use) to implement your own agent loop. Each "agent" is a loop of API calls with its own system prompt and tool set. Nesting is just function calls.
- **Depth support: Unlimited.** You control everything.
- **Integration with your plugins:** Partial. You can reuse MCP server tools by connecting to them from your orchestrator. CLAUDE.md and hooks don't apply (those are Claude Code features).
- **Migration cost:** High. You're building an agent framework from scratch.
- **Production readiness:** As production-ready as you make it. Many teams do this.
- **Tradeoffs:** Maximum flexibility, maximum effort. The Claude Agent SDK is essentially this but packaged — consider building on top of it rather than raw API.

---

## Recommendation Matrix

| Approach | Depth>1 | Plugin Compat | Migration Cost | Production Ready |
|---|---|---|---|---|
| Claude Agent SDK (as-is) | No | Excellent | None | Yes |
| Claude Agent SDK + custom layer | Yes | Good | Medium | You build it |
| MCP "agent spawner" server | Yes | Excellent | Medium | You build it |
| LangGraph | Yes | Poor | High | Yes |
| AutoGen | Yes | Poor | High | Yes (with churn) |
| CrewAI | Partial | Poor | Medium | Yes (reliability?) |
| OpenAI Agents SDK | Yes (beta) | Poor | High | Beta |
| Custom orchestrator | Yes | Partial | High | You build it |

---

## Recommended Path

**Short-term (now):** Build an MCP server that acts as a "deep agent spawner." This lets subagents request deeper delegation through a tool call that your MCP server handles externally (via Claude Agent SDK or raw API). You keep your entire plugin ecosystem intact. The MCP server pattern is:

1. Subagent calls `mcp__agent_spawner__delegate(task, depth, tools)`.
2. MCP server creates a new Claude Agent SDK session with its own system prompt and tools.
3. Result flows back through the MCP tool response.
4. Depth is tracked and capped by your MCP server (not Claude Code).

**Medium-term (watch):** Monitor Anthropic's roadmap. The depth=1 cap is intentional (safety, cost control), but agent teams are in "research preview" — deeper nesting may come. The GitHub issue [#32731](https://github.com/anthropics/claude-code/issues/32731) tracks the teammate tool restriction documentation gap.

**Long-term (hedge):** If you ever need orchestration decoupled from Claude Code (CI/CD pipelines, server-side batch jobs), LangGraph with Claude as the LLM backend gives you the most mature depth>1 support. Keep it as a known escape hatch, not an immediate migration target.

---

## Sources

- [Claude Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Claude Agent SDK Subagents](https://platform.claude.com/docs/en/agent-sdk/subagents)
- [Claude Code Sub-agents](https://code.claude.com/docs/en/sub-agents)
- [Claude Code Agent Teams](https://code.claude.com/docs/en/agent-teams)
- [Claude Code Issue #32731 — Teammate tool restrictions](https://github.com/anthropics/claude-code/issues/32731)
- [Claude Code Issue #4182 — Sub-Agent Task Tool not exposed for nested agents](https://github.com/anthropics/claude-code/issues/4182)
- [Building Agents with Claude Agent SDK (Anthropic blog)](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk)
- [LangGraph Hierarchical Agent Teams Tutorial](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/hierarchical_agent_teams/)
- [langgraph-supervisor-py (GitHub)](https://github.com/langchain-ai/langgraph-supervisor-py)
- [LangGraph Multi-Agent Workflows (Blog)](https://blog.langchain.com/langgraph-multi-agent-workflows/)
- [AutoGen Teams Documentation](https://microsoft.github.io/autogen/stable//user-guide/agentchat-user-guide/tutorial/teams.html)
- [AutoGen v0.4 Research Article](https://www.microsoft.com/en-us/research/articles/autogen-v0-4-reimagining-the-foundation-of-agentic-ai-for-scale-extensibility-and-robustness/)
- [CrewAI Hierarchical Process Docs](https://docs.crewai.com/en/learn/hierarchical-process)
- [OpenAI Agents SDK Multi-Agent Orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- [OpenAI Agents SDK Handoffs](https://openai.github.io/openai-agents-python/handoffs/)
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
