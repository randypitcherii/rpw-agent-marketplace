---
name: generate-backlog
description: Dispatch 2-3 PM agents with complementary lenses over a target repo's product goal to produce a deduplicated, prioritized ENGINEERING BACKLOG of feature proposals, with a hard user checkpoint before filing. Trigger on "generate a backlog", "file a prioritized backlog", "PM agents to propose features", "propose a backlog for <repo>". NOT one known issue (`gh`/marketplace-feedback), NOT an existing engineering backlog (wave-supervisor), and NEVER the task board (personal tasks — human-todo).
---

# Generate Backlog

Turn a one-paragraph product goal into a prioritized, ready-to-file **engineering backlog** for a target repo (never the task board — `docs/process/task-vocabulary.md`): derive 2–3 complementary product-manager lenses from the goal, dispatch one read-only PM agent per lens, synthesize their proposals (merge, dedupe, rank), then **stop at a hard user checkpoint before filing anything**.

Pipeline: intake → derive lenses → dispatch PM agents → synthesize → **user checkpoint** → file → hand off.

## 1. Intake (required args)

- **Target repo** — `owner/name` or a local checkout. Verify access: `gh repo view <owner/name>`.
- **Product goal** — one paragraph. If it's missing or too vague to derive distinct lenses, ask before dispatching; don't invent a goal.

Gather once, up front (this snapshot is shared with every PM agent):

- Existing issues: `gh issue list --repo <owner/name> --state all --limit 200 --json number,title,state,labels` — the dedupe baseline.
- Label conventions: `gh label list --repo <owner/name>` (type/priority/status schemes).
- Vision context: README, `docs/`, ADRs, AGENTS.md/CLAUDE.md if present.

## 2. Derive lenses

Pick 2–3 **complementary** lenses from the goal — angles that partition the product surface with minimal overlap (e.g. "automation workflows" vs "account intelligence"; "authoring UX" vs "operations/reliability" vs "integrations"). State the chosen lenses and a one-line rationale each before dispatching. Two lenses is the floor (a single lens defeats the fan-out); three is the cap.

## 3. Dispatch PM agents

Compose over the `subagent-dispatch` skill — its research-task conventions govern the mechanics: read-only agents, dispatched in ONE message, `run_in_background: true`, max 3, model per its model-selection guidance (Sonnet default; Opus for genuinely ambiguous domains), a Context block in every prompt, and its Result Format. Use `description: "pm-{lens-slug}"`. This skill adds only the PM-specific payload (prompt template in [reference.md](reference.md)):

- **Fixed proposal shape** — every proposal uses exactly: Problem / Scope sketch / Acceptance / Safety / Dependencies / Size. 3–6 proposals per lens; fewer strong proposals beat padded lists.
- **Mandatory dedupe** — diff every candidate against the existing-issue snapshot (all states, including closed). For a near-duplicate: cite the issue number and either propose the *delta* as an extension or drop it. Never re-propose closed-as-wontfix work without flagging it.
- **Dependency declarations** — each proposal names what it depends on: other proposals in the batch, existing blocked issues, and missing credentials/infrastructure ("blocked on X API access"). Unknowable-without-credentials items are proposed as *blocked*, not silently omitted.
- **Read-only** — PM agents never edit files and never run `gh issue create`. Proposals come back in the agent's final message only.

### Research sources — Glean degrades gracefully

Glean MCP is the preferred domain-research tool **but it is org-internal**: this is a public plugin and most users won't have it. Treat Glean as optional:

- **Glean available** → use it for domain/company research behind the goal.
- **Glean absent** (tool not present, or auth fails) → fall back to repo-local sources: README, `docs/`, ADRs, issue and PR history, the code itself; plus web search if the harness provides it.

Never block, fail, or ask the user to install Glean. Agents without it note "researched from repo-local sources (+ web) only" in their result so the synthesis step knows the evidence base.

## 4. Synthesize

The dispatching agent (you, not a subagent) owns synthesis:

1. **Merge** all lens outputs into one candidate list.
2. **Dedupe across lenses** — agents can't see each other, so overlap is expected. Merge overlapping proposals, keeping the sharper Problem statement and the union of good acceptance criteria.
3. **Second dedupe pass** against existing issues — the cross-lens merge can recreate something an individual agent correctly skipped.
4. **Rank** by impact vs effort, dependency order (prerequisites before dependents), and goal alignment. Map each to the target repo's label conventions (type + priority).
5. **Mark blocked items** explicitly — they get filed too (with the blocker named), but ranked and labeled so a wave planner won't dispatch them.

## 5. User checkpoint — HARD GATE

Present the final ranked list: per proposal — title, one-line summary, priority, proposed labels, dependencies/blocked-on. Then ask for explicit approval.

**Never run `gh issue create` (or any issue-writing command) without the user's explicit approval of the final list.** No exceptions: not in headless/unattended runs (stop and hand off the list instead), not for "just the obvious ones", not because an agent pre-formatted the command. Support edits at the checkpoint — drop, merge, reword, reprioritize — and re-present if the changes are material.

## 6. File

After approval only: create each approved issue with body = the full proposal shape and the repo's labels. A handful → file inline; a large batch → minion fan-out per the `subagent-dispatch` skill (minions receive the exact, already-approved `gh issue create` payloads — no drafting authority). Report every created issue URL.

## 7. Hand off — pairs with wave-supervisor

A generated engineering backlog is wave fuel: offer to feed the filed issues straight into the `wave-supervisor` skill for batch-dispatch (or single-issue dispatch via the `dispatch-launch` skill / `/build`). Preserve the dependency and blocked annotations in the issue bodies — the wave planner uses them to group conflict surfaces and skip blocked work.

See [reference.md](reference.md) for the proposal-shape template, the PM-agent prompt template, and a worked example.
