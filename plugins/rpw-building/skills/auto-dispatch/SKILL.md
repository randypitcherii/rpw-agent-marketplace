---
name: auto-dispatch
description: Auto-dispatch subagents for research, debugging, and minion tasks outside /build sessions. Teaches the agent to recognize request patterns and spawn the right subagent type.
---

# Auto-Dispatch Subagents

When you are NOT inside a `/build` session, automatically dispatch subagents for qualifying requests. This keeps the main conversation context clean and leverages parallel fan-out for thoroughness.

**This skill does NOT apply during `/build` sessions** — the build lifecycle has its own dispatch protocol via the `subagent-dispatch` skill. See that skill for the canonical role reference table, model selection guide, and shared guardrails.

## Inline-First Threshold

**Check this FIRST, before evaluating any dispatch category.**

If you can answer the request with 3 or fewer tool calls using context you already have, handle it inline. Do not dispatch.

**Stays inline (handle directly):**
- Reading a single file or checking one config value
- A single `grep` / `glob` search across the codebase
- A quick git command (`git log`, `git status`, `git diff`)
- Factual questions answerable from memory or one lookup
- Any task completable in ≤3 sequential tool calls

**Gets dispatched:**
- Needs 4+ distinct sources, files, or searches to answer
- Requires parallel investigation of multiple independent angles
- Benefits from fan-out (Research Lead + Workers)
- Involves a bug where root cause is unknown and multi-path exploration is needed

If you're uncertain, bias toward inline. Dispatch is for thoroughness and parallel scale — not for offloading simple lookups.

## When to Auto-Dispatch

Evaluate every user request against these three categories. If a request matches, dispatch immediately — do not ask permission.

### 1. Minion Tasks (Haiku)

**Trigger patterns:** Simple, bounded, low-risk tasks that don't require deep reasoning.

- Bead creation (`bd create` with known parameters)
- File renaming, moving, or metadata updates (version bumps, config field changes)
- Simple lookups ("what's the value of X in file Y?")
- Formatting, linting, or generating boilerplate from a known template

**Do NOT minion-dispatch:** Anything requiring judgment, multi-file coordination, or user-facing decisions.

```
Agent(
  name: "minion-{action}",
  description: "{3-5 word summary}",
  model: "haiku",
  mode: "bypassPermissions",  // omit for read-only tasks
  run_in_background: false,
  prompt: "You are a Minion handling a simple task.

    ## Task
    {exact-action-to-perform}

    ## Context from conversation
    - Goal: {what the user is ultimately trying to accomplish}
    - Files/paths examined: {list any already examined, or 'none'}
    - Approaches tried/rejected: {list any, or 'none'}
    - User preferences/constraints: {list any stated, or 'none'}

    ## Constraints
    - Complete this single action and return the result.
    - Do not ask questions — make reasonable assumptions.
    - Do not modify files outside the specified scope.
    - Return a brief result: what you did, what changed."
)
```

**Notes:**
- Minions run in foreground (they're fast) and do NOT use worktree isolation.
- Include `mode: "bypassPermissions"` only when the minion needs to edit files.

### 2. Research Tasks

**Trigger patterns:** Requests requiring investigation, exploration, or gathering information from multiple sources.

- "Research X", "Compare X vs Y", "What are the options for X?"
- "How does X work in this codebase?"
- "What's the best approach for X?" (when it requires exploration, not just opinion)
- Technology evaluation, architecture review, or any question benefiting from 3+ sources

**Do NOT research-dispatch:** Simple factual questions answerable from one file read or one search.

**Single-topic research** — dispatch one agent (Opus):

```
Agent(
  name: "research-{topic-slug}",
  description: "{3-5 word summary}",
  model: "opus",
  run_in_background: true,
  prompt: "You are a Research Lead investigating a topic.

    ## Research Question
    {question-or-topic}

    ## Context from conversation
    - Goal: {what the user is ultimately trying to accomplish}
    - Files/paths examined: {list any already examined, or 'none'}
    - Approaches tried/rejected: {list any, or 'none'}
    - User preferences/constraints: {list any stated, or 'none'}

    ## Desired Output
    {format: summary, comparison table, recommendation, etc.}

    ## Instructions
    - Investigate the topic thoroughly using all available tools (search, web, file reads).
    - Use multiple parallel tool calls per response to maximize coverage.
    - Cite specific files, URLs, or sources for key claims.
    - If a subtopic yields insufficient information, note the gap rather than guessing.
    - If you encounter blocking errors, return immediately with what you have rather than retrying indefinitely.
    - Return your findings using the structured result format defined in this skill."
)
```

**Multi-angle research** — dispatch multiple agents (Sonnet) in parallel from the main conversation, then synthesize their results yourself:

```
// Dispatch all in ONE message for parallel execution
Agent(name: "rw-{topic}-angle-1", model: "sonnet", run_in_background: true, prompt: "Research {subtopic A}...")
Agent(name: "rw-{topic}-angle-2", model: "sonnet", run_in_background: true, prompt: "Research {subtopic B}...")
Agent(name: "rw-{topic}-angle-3", model: "sonnet", run_in_background: true, prompt: "Research {subtopic C}...")
```

**Notes:**
- Research agents run in background and NEVER use worktree isolation (read-only).
- **Subagents cannot spawn subagents** — the Agent tool is not available at depth=1. For parallel fan-out, dispatch multiple workers directly from the main conversation (depth=0) and synthesize results yourself.
- Max 3 parallel research agents per topic.

### 3. Debugging Tasks (Opus)

**Trigger patterns:** Bug reports, failures, and investigation requests.

- "Why is X broken?", "This test is failing", "I'm getting error X"
- Stack traces, error messages, or unexpected behavior reports
- "Debug this", "Investigate this failure", "What's causing X?"

**Do NOT debug-dispatch:** Issues where the user clearly already knows the fix and just wants you to implement it.

```
Agent(
  name: "debug-{issue-slug}",
  description: "{3-5 word summary}",
  model: "opus",
  run_in_background: true,
  prompt: "You are a Debug Lead investigating an issue.

    ## Problem
    {problem-description-and-any-error-output}

    ## Context
    {relevant-files-or-components}

    ## Context from conversation
    - Goal: {what the user is ultimately trying to accomplish}
    - Files/paths examined: {list any already examined, or 'none'}
    - Approaches tried/rejected: {list any, or 'none'}
    - User preferences/constraints: {list any stated, or 'none'}

    ## Instructions
    Follow systematic debugging methodology:
    1. Reproduce: confirm the issue exists and identify exact failure point.
    2. Hypothesize: form 2-3 likely root cause hypotheses.
    3. Test hypotheses: gather evidence for/against each using parallel tool calls to explore multiple code paths simultaneously.
    4. Root cause: identify the confirmed root cause with evidence.
    5. Fix recommendation: propose a specific fix with file paths and code changes.

    ## Constraints
    - Do NOT implement fixes — only diagnose and recommend.
    - Do NOT edit any files.
    - If you encounter blocking errors, return immediately with what you have rather than retrying indefinitely.
    - Return: root cause, evidence, recommended fix, and any related issues discovered.
    - Return your findings using the structured result format defined in this skill."
)
```

**Notes:**
- Debugging Leads run in background and NEVER edit files or use worktree isolation (diagnose only).
- The main conversation agent implements the fix after reviewing the diagnosis.
- If the debug agent discovers related issues, those become new beads.

## Guardrails

All guardrails from `subagent-dispatch` skill (section 5) apply here, plus these auto-dispatch specifics:

- **Max fan-out**: 5 Minions per batch (Research Worker limit of 3 is inherited from `subagent-dispatch`).
- **No file edits** from Research or Debug agents — they are read-only.
- **Background agents**: Always tell the user what was dispatched and why. Don't silently spawn.
- If an auto-dispatched agent reveals work needing implementation, create a bead and suggest `/build` for non-trivial work.
- **Don't over-dispatch**: A simple `grep` or single file read does not need a Research Lead.
- **Don't dispatch for conversation**: Questions that need clarification or discussion stay in the main conversation.

## Error Handling

When an agent fails, returns empty/incomplete results, or errors:
1. Report the failure to the user immediately — include what the agent was trying to do and what went wrong.
2. For partial results, present what is available and explicitly note what is missing.
3. Offer alternatives: retry with a different approach, handle the task inline, or skip if optional.

## Result Format

Research Leads and Debug Leads must return results using this structured completion report. Minions are exempt — they just return what they did.

### Completion Report Template

```
**Status**: success | partial | failed
**Confidence**: high | medium | low

**Summary**
2-3 sentence answer to the original question or diagnosis.

**Findings**
- Key finding 1 (with source/file reference)
- Key finding 2 (with source/file reference)
- ...

**Gaps**
- What couldn't be determined and why
- Missing information or inaccessible sources

**Follow-up**
- Recommended next actions
- Beads to create (if applicable)
```

### Presentation Rules (for the main agent receiving results)

Based on the reported confidence level, present results to the user as follows:

- **High confidence**: Present the summary only. Offer to share full findings on request.
- **Medium confidence**: Present the summary + key findings + gaps. Let the user decide next steps.
- **Low confidence**: Present the full report with explicit caveats. Do not present partial findings as conclusions.
