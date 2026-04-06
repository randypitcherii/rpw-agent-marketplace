---
date: 2026-03-13
status: draft
review_by: 2026-04-13
---

# Auto-Dispatch Patterns for Multi-Agent LLM Systems

## Research Question

What are the best patterns for automatically routing user requests to specialized sub-agents, and how does our current `auto-dispatch` skill compare?

## 1. Trigger Detection Patterns

### What Production Systems Use

| System | Detection Method | How It Works |
|--------|-----------------|--------------|
| **Anthropic orchestrator-workers** | LLM-as-router | The orchestrator LLM classifies the request and decides which worker(s) to invoke. No keyword matching — pure intent classification via the model itself. |
| **AWS Multi-Agent Orchestrator** | Classifier agent + agent descriptions | A dedicated classifier agent receives the user input plus all registered agent descriptions. It returns the best-match agent ID. Falls back to a default agent if confidence is low. |
| **OpenAI Swarm** | Function-based handoff | Agents return `handoff()` functions — the routing decision is made by the current agent as a tool call, not by a central router. Fully decentralized. |
| **LangGraph** | Conditional edges in a graph | Routing is a graph node with conditional edges. The condition can be LLM-classified, rule-based, or hybrid. Supports `Command(goto="agent_name")` for explicit transfers. |
| **AutoGen** | Handoff messages | Agents emit `HandoffMessage` objects targeting another agent by name. The group chat manager routes based on these messages. |
| **CrewAI** | Flow decorators + router conditions | `@router` decorator on flow methods returns a string label that maps to the next listener. Can be LLM-classified or rule-based. |

### Recommendation for Auto-Dispatch

**Use LLM-as-router, not keyword matching.** Our current SKILL.md already does this implicitly (the model reads the trigger patterns and decides), which is correct. The "trigger patterns" section serves as guidance to the model, not as a regex engine. This matches Anthropic's own approach and AWS Multi-Agent Orchestrator.

**Add a "don't dispatch" signal.** The current skill lists when TO dispatch but the "do NOT dispatch" bullets are scattered. Consolidate into a single decision: "If the task can be completed in <3 tool calls with information already in context, handle inline."

**Add confidence-based fallback.** AWS Multi-Agent Orchestrator routes to a default agent when the classifier is unsure. Our equivalent: if the dispatch category is ambiguous, ask the user rather than guessing.

## 2. Dispatch Taxonomy

### What Other Systems Use

| System | Categories | Notes |
|--------|-----------|-------|
| **Anthropic multi-agent research** | Lead + Workers (2 tiers) | Single taxonomy: research lead decomposes, workers execute. No category distinction — workers are fungible. |
| **AWS Multi-Agent Orchestrator** | Per-domain agents (tech, health, finance, etc.) | Open taxonomy — any number of specialist agents registered. Classifier picks the best match. |
| **OpenAI Swarm** | Per-function agents (sales, support, triage, etc.) | Domain-based, not task-type-based. Each agent owns a business function. |
| **LangGraph** | Supervisor + workers OR network of peers | Workers are defined by capability, not by task type. |
| **AutoGen** | Team-based (swarm, round-robin, selector) | Teams of agents with different selection strategies. |

### Assessment of Our 3-Category Model

Our current taxonomy (Minion / Research / Debug) is **task-type-based**, which is the right approach for a developer tool where the user's intent maps cleanly to task types. Domain-based routing (like Swarm's sales/support split) doesn't apply here.

**The 3 categories are sufficient but need boundary refinement:**

| Category | Current Gap | Recommendation |
|----------|-------------|----------------|
| **Minion** | Well-defined. No gap. | Keep as-is. |
| **Research** | Covers investigation well but doesn't distinguish "explore options" from "gather facts from external sources." | Split trigger guidance into (a) codebase exploration and (b) external research, but keep them as one dispatch category since the execution pattern is identical. |
| **Debug** | Well-defined. No gap. | Keep as-is. |
| **MISSING: Review/Audit** | No category for "review this PR," "audit this config," "check this for security issues." These are read-only like research but structured differently — they need a checklist, not a synthesis. | Add as a 4th category or fold into Research with a distinct prompt template. |
| **MISSING: Draft/Generate** | No category for "write a doc," "draft an RFC," "generate test data." These produce artifacts but don't require /build's full lifecycle. | Consider adding. Currently these fall through to "do it directly" which works but loses the context-isolation benefit. |

**Verdict:** Stay with 3 categories for now. The "review" pattern can use the Research Lead template with a checklist-focused prompt. Draft/generate tasks are better handled inline since they typically need conversational iteration. Revisit if usage patterns show these categories being dispatched incorrectly.

## 3. Context Handoff

### Framework Patterns

| Pattern | Used By | How It Works |
|---------|---------|--------------|
| **Self-contained prompt** | Anthropic subagents, our current system | Each subagent gets a complete prompt with all needed context. No shared memory. The orchestrator is responsible for assembling the prompt. |
| **Shared message history** | AutoGen, LangGraph | Agents share a message list. Each agent sees the full conversation (or a filtered subset). Risk: context pollution. |
| **Structured state object** | LangGraph (graph state), CrewAI (flow state) | A typed state dict is passed between agents. Each agent reads/writes specific keys. Clean but requires schema upfront. |
| **Handoff message** | OpenAI Swarm, AutoGen | The transferring agent writes a handoff message describing what the next agent should know. Conversational but lossy. |

### Recommendation

**Self-contained prompt is correct for our system.** This is validated by:
- Anthropic's own guidance: "subagents need self-contained prompts since they have no shared memory"
- Our adversarial analysis finding that this is a strength, not a limitation
- The fact that our subagents are fire-and-forget, not conversational peers

**Improve the handoff content with a checklist:**

Every auto-dispatch prompt should include:
1. **The user's exact words** (quoted, not paraphrased) — prevents intent drift
2. **Relevant file paths** already known to the main agent
3. **What the main agent already tried** (if anything) — prevents redundant work
4. **Desired output format** — summary, comparison, diagnosis, etc.
5. **Scope boundaries** — what NOT to investigate

The current SKILL.md templates include items 1, 4, and 5 but miss 2 and 3. Add them.

## 4. Result Integration

### Framework Patterns

| Pattern | Used By | Tradeoffs |
|---------|---------|-----------|
| **Raw return** | OpenAI Swarm | Simple but floods the orchestrator's context. |
| **Structured report** | Our adversarial analysis recommendation | Parseable, consistent, but requires discipline from subagents. |
| **Summary + full artifact** | Anthropic multi-agent research | Lead synthesizes worker outputs into a summary; raw data available on request. |
| **Confidence-scored results** | AWS Multi-Agent Orchestrator | Each result has a confidence score; low-confidence results get flagged for human review. |

### Recommendation

**Require structured completion reports for all dispatch categories:**

```
## Result
- **Status:** success | partial | insufficient-data
- **Confidence:** high | medium | low
- **Summary:** {2-3 sentence answer}
- **Key Findings:** {bullet list}
- **Sources:** {file paths, URLs, or evidence}
- **Gaps:** {what couldn't be determined}
- **Follow-up Suggested:** {yes/no + what}
```

**Integration rules:**
- **High confidence + success**: Present the summary to the user. Offer to show details.
- **Medium confidence**: Present summary with explicit caveats. Show key evidence inline.
- **Low confidence or partial**: Present what was found, flag the gaps, and ask the user how to proceed.
- **Follow-up suggested**: Create a bead if it's implementation work, or note it for the user.

The current SKILL.md doesn't specify result format for Research or Debug leads. This is the biggest actionable gap.

## 5. Patterns We Should Steal

### From OpenAI Swarm: Decentralized Handoff
Swarm lets the *current* agent decide to hand off, rather than a central router deciding upfront. For auto-dispatch, this means: if a Research Lead discovers a bug during investigation, it should be able to flag "this needs a Debug dispatch" in its result, rather than the main agent needing to re-classify.

**Action:** Add to the Research Lead template: "If you discover a bug or failure during research, note it as a follow-up item with category 'debug' — do not attempt to debug it yourself."

### From AWS Multi-Agent Orchestrator: Agent Descriptions as Router Input
Each agent has a description, and the classifier uses these descriptions to route. This is more maintainable than hardcoding routing rules.

**Action:** Our skill descriptions already serve this purpose via Claude's skill matching. No change needed, but ensure skill descriptions stay precise.

### From LangGraph: Conditional Edges with Fallback
LangGraph's routing nodes can have a default/fallback edge. If no agent matches, the request stays with the current node.

**Action:** Our current flow already does this (the last branch in the decision flow is "do it directly"). Explicitly document this as the fallback.

### From Anthropic's Research System: Opus Lead + Sonnet Workers
Using Opus for synthesis and Sonnet for parallel data gathering is the most cost-effective pattern validated at scale (90.2% improvement over single-agent Opus per Anthropic's engineering blog).

**Action:** Already implemented in our Research Lead pattern. No change needed.

## 6. Summary of Actionable Changes

| # | Change | Target File | Priority |
|---|--------|-------------|----------|
| 1 | Add structured result format requirement to Research Lead and Debug Lead templates | `auto-dispatch/SKILL.md` | P0 |
| 2 | Add "user's exact words," "known file paths," and "what was already tried" to all dispatch prompt templates | `auto-dispatch/SKILL.md` | P0 |
| 3 | Add inline-handling threshold: "<3 tool calls with existing context = don't dispatch" | `auto-dispatch/SKILL.md` | P1 |
| 4 | Add confidence-based fallback: "if unsure about category, ask user" | `auto-dispatch/SKILL.md` | P1 |
| 5 | Add cross-category escalation note to Research Lead template (flag bugs for debug dispatch) | `auto-dispatch/SKILL.md` | P2 |
| 6 | Evaluate adding a Review/Audit prompt variant under Research category | `auto-dispatch/SKILL.md` | P2 |

## Sources

- Anthropic: "Building Effective AI Agents" — orchestrator-workers, routing, evaluator-optimizer patterns
- Anthropic: "How we built our multi-agent research system" — Opus lead + Sonnet workers, 90.2% improvement
- Anthropic: "Effective context engineering for AI agents" — context compression at subagent boundaries
- OpenAI Swarm: README — handoff functions, decentralized routing, agent transfer pattern
- AWS Multi-Agent Orchestrator: README — classifier agent, agent descriptions as routing input, confidence-based fallback
- LangGraph: "Multi-agent concepts" — supervisor, network, hierarchical architectures, conditional routing, Command-based handoff
- AutoGen: "Handoffs design pattern" — HandoffMessage protocol, swarm group chat
- CrewAI: "Flows" — @router decorator, flow state, listener-based routing
- GitHub Blog: "Multi-agent workflows often fail" — reliability multiplication, error trap analysis
- Internal: `adversarial-analysis-subagent-worktree.md` — existing gap analysis and P0-P3 recommendations
- Internal: `2026-03-08-subagent-created-subagent-feasibility.md` — depth/fan-out guardrails
- Internal: `2026-03-10-build-subagent-recommendations.md` — prompt templates, completion contracts
