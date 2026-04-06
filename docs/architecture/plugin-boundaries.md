# Plugin Boundary Contract: `rpw-building`, `rpw-working`, `rpw-databricks`

**Status:** Active  
**Last updated:** 2026-03-08

## Purpose

Define durable ownership boundaries between plugins so new work lands in one place, plugins do not drift, and release risk stays low.

> **Canonical scope definitions** live in `CLAUDE.md` at the repo root. This document expands on boundaries, placement rules, and anti-patterns.

## Ownership Model

### `rpw-building` (Build-time enablement)

Owns capabilities that help users configure, extend, or maintain their coding environment and workflows.

Typical scope:
- Setup and configuration workflows (for tools, editor, MCP environment, build commands).
- Plugin/agent/skill authoring guidance.
- Upgrade, diagnostics, and maintenance workflows.
- Conventions and standards for building new capabilities.

### `rpw-working` (Run-time execution)

Owns capabilities that help users perform day-to-day work tasks against real systems and business processes.

Typical scope:
- Operational skills (UCOs, account transitions, troubleshooting, escalations, customer responses).
- Databricks/Salesforce/internal workflow execution.
- User-facing productivity workflows (task execution, reporting, analysis).
- Runtime MCP integrations used to complete work.

### `rpw-databricks` (Databricks-focused execution)

Owns capabilities focused on Databricks-specific work activities and delivery workflows.

Typical scope:
- Databricks product capability routing and validation flows.
- Databricks troubleshooting and performance support workflows.
- Databricks demo/POC workflow orchestration.
- Databricks-first operational guidance that should be separable from general work tooling.

## Contract Rules (Enforceable)

1. **Single owner:** Every skill/command/MCP integration must have one primary plugin owner.
2. **Intent test:** If the main outcome is _build/configure the toolchain_, place in `rpw-building`; if it is _execute general business/field work_, place in `rpw-working`; if it is _Databricks-specific execution_, place in `rpw-databricks`.
3. **No mirrored implementations:** Do not duplicate the same capability in both plugins with minor wording differences.
4. **Shared primitives stay minimal:** Reusable helpers should be abstract, stable, and not carry plugin-specific behavior.
5. **Cross-plugin references are explicit:** If one plugin depends on conventions from the other, link docs rather than copying logic.

## Concrete Placement Examples

- **Goes in `rpw-building`:**
  - "Configure Cursor with `/build` command"
  - "Set up MCP `.env` and auth prerequisites"
  - "Create/maintain agent or skill scaffolding standards"
- **Goes in `rpw-working`:**
  - "Update UCOs and analyze progression gaps"
  - "Draft customer-facing responses from product research"
  - "Maintain human work-backlog setup and task tracking workflows"
- **Goes in `rpw-databricks`:**
  - "Route Databricks requests to troubleshooting/performance/demo workflows"
  - "Coordinate Databricks product capability and validation tasks"
  - "Run Databricks-focused execution patterns with evidence-first outputs"

## Anti-Patterns

- Putting account/customer operational workflows into `rpw-building` because they "use tooling."
- Putting plugin-authoring/setup guidance into `rpw-working` because it "helps work."
- Duplicating Databricks-specific execution guidance in `rpw-working` and `rpw-databricks`.
- Shipping near-identical skills in both plugins to avoid deciding ownership.
- Hiding boundary decisions only in commit messages without updating docs.

## Decision Checklist (Before Adding New Capability)

Use this list before creating or moving any skill/command/MCP server:

1. Is the primary user outcome **build/configure** or **execute work**?
2. Who is the core user in this flow: **plugin builder** or **workflow operator**?
3. Does an existing capability already cover this in either plugin?
4. Could this be a small shared primitive instead of duplicate top-level skills?
5. Did you add or update links/docs so future contributors can find the boundary rule?

If any answer is unclear, default to documenting the choice here (or in an ADR if long-lived architectural impact is broader than plugin boundaries).
