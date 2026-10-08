---
name: rpw-catalog
description: Index of the house skills that are NOT always loaded — Databricks platform/DABs/dbt, harness and auth setup, Omnigent operations, MCP servers and standards, repo/release/versioning/backlog ops, writing and doc style, web UI and browser testing, personal workflow and research. Use when a task looks like house work but no loaded skill covers it, or the user names one of those areas — then `rpw skills show <name>` loads the real skill.
---

# House skill catalog

Only ~20 house skills are installed natively (the measured core — 76% of all skill
loads). The rest live in the repo and are reached from here, in one hop.

## Load a skill from this catalog

```bash
rpw skills show <name>      # print the full SKILL.md — this is the hop
rpw skills list             # every house skill, core vs long-tail, with one-liners
rpw skills list --long-tail # just what this catalog covers
```

No `rpw` on PATH? Read the file directly:
`plugins/rpw-published/skills/<name>/SKILL.md`.

This index covers the `rpw-published` plugin. `rpw skills list` reads the checkout, so in
a full checkout it also shows skills this index does not — that is expected, not drift.

## The long tail, by domain

<!-- generated:index:begin -->

**Databricks platform, DABs & data** — `dabs-environments`, `databricks-apps`, `databricks-jobs`, `databricks-model-serving`, `databricks-uc-connections`, `databricks-workspace-estate`, `dbt-project-standards`, `eval-patterns`

**Harness, proxy & auth setup** — `configure-cursor-build`, `hide-claude-managed-settings`, `mobile-sso`, `reauth-before-error`

**Omnigent operations** — `agentic-improvements-report`, `morning-prep-report`, `omnigent-chief-of-staff`

**MCP servers & standards** — `mcp-setup`, `mcp-standards`

**Writing, doc style & Slack formatting** — `doc-styling`, `document-files`, `simple-english`, `slack-formatting`

**Web UI, visuals & browser testing** — `agent-browser-standards`, `browser-testing-standards`, `demo-capture`, `favicon-standards`, `image-generation`, `raycast-extension-development`, `ui-improvement-cycle`, `web-design`

**Personal workflow & research** — `human-todo`, `notion-calendar-dupe-guard`, `pain-interview`, `shareables-experiment`

**Repo, release & backlog ops** — `agents-md-standards`, `archive-migrated-repo`, `changelog-release-notes`, `checkpoint`, `env-preferences`, `generate-backlog`, `marketplace-feedback`, `multi-project-monorepo`, `oss-contribution-closeout`, `project-readme`, `scrub-repo-history`, `skill-recommender`, `staleness-sweep`, `versioning-standards`

_47 skills. One-line gists: `references/long-tail.md`._
<!-- generated:index:end -->

## How this list stays honest

The index above and `references/long-tail.md` are **generated** from the repo tree plus
the committed core list (`scripts/core-skills.txt`) — never hand-edited:

```bash
uv run --no-project python scripts/gen_core_skills.py          # rewrite both
uv run --no-project python scripts/gen_core_skills.py --check  # verify, exit 1 on drift
```

A new house skill that is neither in the core nor in a catalog index fails the repo gate
(`tests/test_repo_validations.py::TestSkillDistribution`), so nothing can go missing
quietly. The core list itself is regenerated from real usage with
`--refresh-core` (see #1961 and the Q4 recommendation in
`docs/research/2026-09-26-marketplace-helpfulness-audit.md`).
