# Autonomy caps for unattended fan-out (#916)

Claude Code's autonomy defaults moved under us between v2.1.198 and v2.1.221: nested
spawn depth went 1 → 3, a concurrency cap appeared at 20, and background sessions
started committing and pushing without asking. Two unattended routines run daily on
this machine, so "whatever the vendor shipped" was governing wave-scale fan-out by
default. This file is the decision record: the values, the arithmetic behind them,
where they live, and what they do **not** cover.

## Pinned values

| Env var | Value | One-line rationale |
|---|---|---|
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` | `5` | The number SKILL.md §5 already allows (5 Build Workers / 5 Minions) — the harness now enforces the written rule instead of permitting 4× it. |
| `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` | `2` | The deepest pattern this plugin actually ships (`research-lead` → `research-worker`) and not one generation more. |

⚠️ **The var name is `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, not `CLAUDE_CODE_MAX_SPAWN_DEPTH`.**
#916 and its wave brief both name the shorter form. Measured against the installed
CLI (2.1.228): the long name occurs 5 times, including the read site
`if (X.CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH !== void 0) return it`; the short name
occurs **zero** times. Setting the short name is the exact failure the
`automation-standards` liveness-is-not-health rule warns about — a cap that reads as
configured and does nothing.

## Why not the shipped 20 / 3

**Depth is the multiplier, not concurrency.** The concurrency cap is taken from a
per-session registry (`taskRegistry.takeConcurrencySlot()`, default `20` in the same
binary), while depth propagates across generations. Worst-case concurrent agents is
therefore roughly `C + C² + … + C^D`:

| Caps | Theoretical worst case | Deepest documented pattern |
|---|---|---|
| 20 / 3 (shipped) | ~8,400 | — |
| 5 / 2 (pinned) | 30 | 5 |
| 5 / 1 | 5 | breaks `research-lead` |

**Load evidence.** Wave `2026-08-11` ran 5 workers at load ~8 comfortably; 8+
concurrent processes at load ~8.9 was noted as this machine's practical ceiling. The
machine-local LLM proxy that every one of those agents authenticates through
separately sheds load under wide fan-out (`omnigent-ai/omnigent#4447`), so the
blast radius of an accidental 20-wide dispatch is 502s for every concurrent session,
not just the one that fanned out.

**Why depth 2 and not 1.** SKILL.md §5 says subagents are leaves, but
`plugins/rpw-published/agents/research-lead.md` is a shipped subagent whose whole job
is dispatching up to 3 `research-worker`s — depth 1 would break it silently (it would
be told to do the work itself). Depth 2 also preserves supervisor → worker → helper
when wave workers run as Agent-tool subagents rather than detached processes. Depth 3
buys a third generation no documented pattern here uses, at 5× the worst case.

**Raising them.** Concurrency `8` is the highest value the load evidence supports, and
only with a controlled test behind it. Depth `3` needs a documented pattern that
requires a third generation; there isn't one today.

## Where they are set — and why not launchd

`~/.claude/settings.json` → `env`. That block is read by **every** Claude Code session
regardless of launcher, which is what makes it the right home for a cap that has to
reach unattended sessions.

The launchd plists (`automation/launchagents/*.plist.template`) were deliberately left
alone:

- Upstream's `ai.omnigent.host` service is installed outside this repo; it still
  inherits `HOME`, which is precisely what locates `~/.claude/settings.json` for
  sessions under it. The service needs no second copy of the caps.
- `EnvironmentVariables` in any one service reaches only that process tree — not
  interactive sessions, not Raycast-launched ones. A second copy of the same two
  values would cover less and could silently drift from the one every session reads,
  with unestablished precedence between them.
- Detached `claude -p` wave workers inherit the parent env (#1012) **and** are fresh
  top-level sessions, so their depth counter restarts at 0. They pick the caps up from
  `settings.json` like anything else.

## What these caps do not bound

Detached `claude -p` workers are separate top-level sessions. The caps bound the
fan-out *inside* each one; they say nothing about how many the supervisor launches.
That count stays governed by the wave-supervisor's own 5-worker rule — configuration
did not replace it.

## Background sessions and git (#916 AC2/AC3)

Measured from the installed CLI's background-session system prompt (2.1.228), not
inferred. A background session is told to:

- commit before finishing **without asking**, and push if the repo has a remote —
  scoped to a worktree *it entered itself*;
- **"Never push to main/master, force-push, or merge."** (verbatim);
- open a draft PR only "when the task calls for one";
- defer to the user's instructions "in the task, `CLAUDE.md`, or memory" where those
  reserve git;
- **ask first** if it did not enter the worktree itself, or is in the user's own
  checkout.

Reconciled against the house committing rule (global `CLAUDE.md`), which makes routine
integration-branch delivery autonomous and requires confirmation for release/publish
branches, public releases, force-pushes to shared branches, and CI changes on shared
branches:

| Confirm-first item | What stops it unattended | Verdict |
|---|---|---|
| Force-push to a shared branch | Harness prompt: "never … force-push" | ✅ refused in-harness |
| Merging | Harness prompt: "never … merge" | ✅ refused in-harness |
| Push to `main`/`master` | Harness prompt | ✅ (moot here — the integration branch is `production`) |
| Push or PR to `published/<target>` | Auto-mode classifier does not bless publication-target branches; the server ruleset also requires a passing promotion PR | ✅ layered |
| `make publish-promote` / merging a `published/<target>` PR | Production-branch command gate plus protected branch required check; human controls the promotion merge | ✅ mechanical |
| CI changes on a shared branch | Nothing mechanical; instruction-level only | ⚠️ residual |

So the answer to AC2 is: **auto-push targets the branch the session is already on in
its own worktree, and cannot reach a confirm-first branch by merging or force-pushing.**
The one path that could reach one unattended is a task that explicitly asks for a PR
based on a publish branch, and that path is gated by the auto-mode classifier plus the
release gate rather than by the harness's own git rules.

**Stated as unverified:** under `--permission-mode bypassPermissions` the classifier is
out of the path, and no evidence was gathered on whether any unattended routine here
runs that way. Treat the classifier-gated row as protection that holds only in auto
mode.

## Verification status — configured and reasoned, not load-tested

**Measured.** The var names were checked against the installed binary's read sites, so
a set cap is loaded rather than decorative. And the `settings.json` → process-env path
is measured, not assumed: inside an Agent-tool subagent's own tool subprocess,
`env | grep` returns `CLAUDE_CODE_SCROLL_SPEED=3`,
`CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`, and
`CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` — every one of them sourced from that
`env` block and from nowhere else, and inherited across the dispatch boundary. Both cap
names are absent from the same listing, which is what "unset" looks like.

**Unverified, stated as such.** A session started *by launchd* was not probed directly.
The two probes that would close it — spawning a nested `claude -p` with shell access, or
setting the values and re-reading them — are both gated by the auto-mode classifier
without explicit user authorization in-transcript. The inference from the measured path
plus `HOME` in the plist is strong but it is an inference.

**No wide fan-out test was run.** Spawning a >cap fan-out on this machine is the exact
load event the cap exists to prevent, and other wave workers were running. Throttling
is configured and reasoned; it is not demonstrated. A controlled test belongs in its own
issue on an idle machine.
