# Multi-Agent Dispatch Failure Modes: Research Report

**Date:** 2026-03-13
**Scope:** Pitfalls, failure modes, and gaps in our auto-dispatch / subagent-dispatch skills

---

## 1. Academic Foundation: MAST Taxonomy (NeurIPS 2025)

The paper ["Why Do Multi-Agent LLM Systems Fail?"](https://arxiv.org/abs/2503.13657) analyzed 1600+ traces across 7 MAS frameworks and found **41-86.7% failure rates**. Their 14 failure modes in 3 categories:

### Category A: Specification & System Design
| Mode | Description | Relevance to Our Skills |
|------|-------------|------------------------|
| Disobey Task Specification | Agent ignores constraints in its prompt | Our prompts say "do not edit files" but have no enforcement mechanism |
| Disobey Role Specification | Agent acts outside its designated role | Research Lead could start implementing fixes instead of diagnosing |
| Step Repetition | Agent repeats the same action in a loop | No loop-detection in our dispatch; a research worker could re-search the same query |
| Loss of Conversation History | Agent forgets prior context mid-task | Subagents start with fresh context; only the prompt string carries info |
| Unaware of Termination Conditions | Agent doesn't know when to stop | No explicit "you are done when..." criteria in our Research/Debug prompts |

### Category B: Inter-Agent Misalignment
| Mode | Description | Relevance to Our Skills |
|------|-------------|------------------------|
| Conversation Reset | Agent loses track of multi-turn state | N/A for our single-turn dispatch model |
| Fail to Ask for Clarification | Agent guesses instead of flagging ambiguity | Our prompts say "do not ask questions -- make reasonable assumptions" -- this is intentional but risky |
| Task Derailment | Agent drifts to tangential work | Research Workers have no scope constraint beyond the subtopic string |
| Information Withholding | Agent has relevant info but doesn't share it | Workers return summaries; details may be lost in compression |
| Ignored Other Agent's Input | Agent discards input from peers | N/A (our workers don't communicate peer-to-peer) |
| Reasoning-Action Mismatch | Agent's stated plan contradicts its actions | No verification layer checks this |

### Category C: Task Verification
| Mode | Description | Relevance to Our Skills |
|------|-------------|------------------------|
| Premature Termination | Agent stops before completing the task | Background agents may return partial results with no retry |
| No/Incomplete Verification | Agent doesn't validate its own output | No self-check step in our dispatch templates |
| Incorrect Verification | Agent validates against wrong criteria | No explicit acceptance criteria in Research/Debug prompts |

**Key stat:** 79% of failures originate from specification and coordination issues, not technical bugs.

---

## 2. Over-Dispatch: When NOT to Spawn

### What the research says
Anthropic's own [multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) blog reveals: "Early agents made errors like spawning 50 subagents for simple queries." Their fix: explicit guidelines for resource allocation based on query complexity.

### Gaps in our auto-dispatch skill

**Current "Do NOT dispatch" criteria:**
- Minion: "Anything requiring judgment, multi-file coordination, or user-facing decisions"
- Research: "Simple factual questions answerable from one file read or one search"
- Debug: "Issues where the user clearly already knows the fix"

**Missing criteria:**
1. **No cost/complexity threshold.** A question like "how does auth work in this codebase?" could be answered by reading 2-3 files inline, but pattern-matches to research dispatch. Need a heuristic like: "If answerable in <3 tool calls, do it inline."
2. **No user-preference signal.** Some users hate background dispatch for anything. There's no opt-out mechanism or sensitivity setting.
3. **No "I already have the context" check.** If the main agent already has the relevant files in context from prior conversation turns, dispatching a research agent forces a cold restart. The dispatch should check: "Do I already have enough context to answer this?"
4. **Ambiguous boundary between research and implementation advice.** "What's the best approach for X?" might need a 30-second opinion, not a background research lead with 3 workers.

---

## 3. Context Loss: The Telephone Game

### The fundamental constraint
Claude Code subagents start with a **fresh context window**. The only channel from parent to subagent is the `prompt` string in the Agent tool call. ([source](https://code.claude.com/docs/en/sub-agents))

### What gets lost in our templates

| Information Type | Currently Passed? | Risk |
|-----------------|-------------------|------|
| User's exact words | Partially (paraphrased in prompt) | Subtle requirements get dropped |
| Prior conversation context | No | Agent re-discovers what main agent already knows |
| File contents already read | No | Redundant tool calls, wasted tokens |
| User preferences from CLAUDE.md | Auto-inherited by subagents | OK -- this one works |
| Tool output from prior turns | No | Research agent can't build on earlier findings |
| Rejection/correction history | No | Agent may repeat approaches the user already rejected |

### Concrete failure scenario
1. User says: "Research how to implement X, but NOT using approach Y -- we tried that and it failed."
2. Main agent dispatches Research Lead with prompt: "Research how to implement X."
3. Research Lead dispatches 3 workers. Worker 2 researches approach Y in depth.
4. User receives a report recommending approach Y.

### Recommendations
- **Include negative constraints explicitly** in dispatch prompts: "The user has rejected: {list}."
- **Include a conversation summary** (not transcript) in the prompt: last 3-5 user messages, key decisions made.
- **Pass file paths already explored**, so subagents don't re-read them but can reference them.

---

## 4. User Experience Pitfalls

### Background agent problems
| Problem | Current Mitigation | Gap |
|---------|-------------------|-----|
| Agent takes too long, user moves on | None | No timeout, no progress updates, no cancellation guidance |
| Results don't match expectations | None | No preview/confirmation before dispatch |
| Silent failure (agent errors out) | None | No explicit error reporting protocol |
| User disagrees with dispatch decision | "dispatch immediately -- do not ask permission" | No opt-out, no undo |
| Multiple background agents finish at different times | None | Results arrive out of order with no synthesis |

### What Anthropic learned
From their [effective harnesses](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) blog: compound errors in agentic systems mean minor issues cause agents to explore entirely different trajectories. One failed step derails the whole chain.

### Recommendations
1. **Announce before dispatch:** The skill says "tell the user what was dispatched and why" -- good, but add estimated completion time and how to check status.
2. **Add a "dispatch preview" mode:** For the first N uses or for complex dispatches, show the user the dispatch plan and let them approve/modify before spawning.
3. **Define error reporting:** When a subagent fails, the main agent should: (a) report what failed, (b) report what partial results exist, (c) offer to retry with adjusted parameters or handle inline.
4. **Result synthesis protocol:** When multiple background agents complete, synthesize results before presenting -- don't dump raw agent outputs sequentially.

---

## 5. Depth and Fan-Out Problems

### The platform constraint
Claude Code **prevents subagents from spawning subagents** at the platform level. ([source](https://github.com/anthropics/claude-code/issues/4182)) This means our skill's "nested dispatch" pattern (Research Lead -> Research Workers) **may not actually work** as written.

### Critical finding: Nested dispatch may be impossible
Our auto-dispatch skill instructs the Research Lead to:
```
Dispatch up to 3 Research Workers (Sonnet) in parallel:
  Agent(name: 'rw-{topic-slug}-{n}', ...)
```

But Claude Code docs state: "Subagents cannot spawn other subagents." If this constraint is enforced, the Research Lead (itself a subagent) **cannot spawn Research Workers**. The entire Lead -> Worker fan-out pattern is architecturally impossible.

**This is the single most critical gap in our implementation.** The skill describes a pattern that the platform may not support.

### Workarounds if nested dispatch is blocked
1. **Flat fan-out from main agent:** Main agent spawns the Research Lead AND the Workers directly, with the Lead serving as synthesizer only.
2. **Sequential chain:** Main agent spawns Workers first, collects results, then spawns a Synthesizer agent.
3. **Single deep agent:** Use one Opus agent with a long context window instead of Lead + Workers.

### Cost guardrails that actually work (from industry)
- **Token budgets per agent:** Set a max token spend per subagent invocation.
- **Wall-clock timeouts:** Kill agents that exceed N minutes.
- **Fan-out caps:** Our 3-worker and 5-minion limits are good but need enforcement, not just documentation.
- **Escalation triggers:** "If 3+ workers fail in the same cycle, stop and ask the human" (already in subagent-dispatch -- good).

---

## 6. Specific Gaps in Our Implementation

### auto-dispatch SKILL.md

| Gap | Severity | Recommendation |
|-----|----------|----------------|
| Nested dispatch (Lead->Workers) may not work on Claude Code platform | **Critical** | Verify empirically; redesign if blocked |
| No termination criteria in Research/Debug prompts | High | Add "You are done when: {criteria}" to templates |
| No conversation context forwarding | High | Add conversation summary to dispatch prompt template |
| No cost/complexity threshold for dispatch decisions | Medium | Add heuristic: "If <3 tool calls, handle inline" |
| No timeout or progress mechanism | Medium | Document expected duration; add status-check guidance |
| No user opt-out for auto-dispatch | Medium | Add a "dispatch: manual" preference signal |
| "Do not ask questions" instruction suppresses useful clarification | Medium | Change to: "Flag critical ambiguities in your result, but do not block on them" |
| No output validation step | Medium | Add self-check: "Before returning, verify your result addresses the original question" |
| No handling of conflicting results from parallel workers | Low | Add synthesis instruction: "If workers disagree, present both views with evidence" |

### subagent-dispatch SKILL.md

| Gap | Severity | Recommendation |
|-----|----------|----------------|
| Same nested dispatch concern (Build Worker -> Research Lead at depth 2) | **Critical** | Verify platform support for depth-2 spawning |
| No token budget per worker | Medium | Add advisory: "Workers should complete within ~50K tokens" |
| `git diff --cached` secret check is advisory, not enforced | Medium | Add a PR Security Guard as mandatory step, not optional |
| No protocol for workers that hang indefinitely | Medium | Add timeout guidance: "If no result in 10 min, consider failed" |
| Shared file conflict detection is manual | Low | The "NEVER modify same files in parallel" rule depends on Build Lead judgment |

---

## 7. Concrete Recommendations (Priority Order)

1. **Verify nested dispatch works.** Spawn a test Research Lead and have it try to spawn a Worker. If it fails, redesign the fan-out pattern to be flat (main agent spawns all agents).

2. **Add termination criteria to all dispatch templates.** Every agent prompt should include: "You are done when: {explicit criteria}. Do not continue past this point."

3. **Add conversation context to dispatch prompts.** Include: (a) last 3 user messages summarized, (b) key decisions/rejections, (c) files already explored.

4. **Add a complexity gate before dispatch.** Before spawning a Research Lead, ask: "Can I answer this in <3 tool calls with context I already have?" If yes, skip dispatch.

5. **Add error reporting protocol.** When a subagent returns failure or partial results, the main agent must: report what failed, present partial results, offer retry or inline handling.

6. **Add output self-validation.** Before returning, every agent should verify: "Does my output address the original question? Have I included sources/evidence?"

7. **Add user opt-out.** Respect a user signal (e.g., in CLAUDE.md) like `dispatch-mode: manual` that requires confirmation before auto-dispatching.

---

## Sources

- [Why Do Multi-Agent LLM Systems Fail? (NeurIPS 2025)](https://arxiv.org/abs/2503.13657)
- [Why Multi-Agent LLM Systems Fail and How to Fix Them (Augment Code)](https://www.augmentcode.com/guides/why-multi-agent-llm-systems-fail-and-how-to-fix-them)
- [How we built our multi-agent research system (Anthropic)](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Effective harnesses for long-running agents (Anthropic)](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Building effective agents (Anthropic)](https://www.anthropic.com/research/building-effective-agents)
- [Claude Code subagents docs](https://code.claude.com/docs/en/sub-agents)
- [Nested agent spawning issue #4182](https://github.com/anthropics/claude-code/issues/4182)
- [Teammates restriction issue #32731](https://github.com/anthropics/claude-code/issues/32731)
