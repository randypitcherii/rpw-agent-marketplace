---
name: eval-patterns
description: Run a live, multi-arm, multi-model MLflow eval campaign without losing the data to infra. Use when planning or running paid eval sweeps against a task bank (baseline / incremental / final), comparing prompt or tooling arms across models, choosing N and a task slice, or analyzing sweep results — and when a run dies of expired auth, 429 storms, a starved SQL warehouse, or a wedged wrapper. Covers pre-flight, ops rules, and trace-SQL analysis.
---

# Live eval campaigns — the house way

Live eval campaigns do not fail on methodology. They fail on infra: expired tokens, quota
storms, a starved warehouse, shared env files repointed mid-run — and then on an analysis
layer that assumed the runs stayed intact. The first campaign (wave `2026-08-23-token-eff`,
#1244/#713/#714) paid that tuition across ~2 days and 334 trials. Everything here is what
survived.

## What mattered vs what didn't

| Mattered | Didn't |
|---|---|
| **UC trace tables** as the unit of truth (per-trial pass/error/tokens) | Run-level metrics and run artifacts — segmented sweeps fragment them |
| Fresh OAuth token **per task invocation** | Elaborate segment topology to dodge the 60-min TTL |
| Explicitly exported env in every run script | `dev.env` / any shared env file (it got repointed mid-wave; 6 trials landed in the wrong experiment) |
| Frozen task slice + paired per-task ratios | A slice re-chosen per sweep; run-level pivots; MLflow-registered datasets |
| A 4-trial pilot matrix before any sweep | LLM judges on a code-checkable task bank |
| Counting tokens on **errored** trials | Write-once baseline-id guards (every real script bypassed them) |
| Concurrency 2 | Concurrency 4 (429 storm + keychain race, #491) |

The analysis tool built to navigate runs (`compare_arms.py`) was abandoned mid-wave for one
SQL statement. Build the SQL first next time.

## Pre-flight checklist — every item burned this repo once

Run all of it before the first paid trial. Ten minutes here beats a 120-trial redo.

1. **Endpoints exist and bind tools** on the target workspace(s) — probe served / chats /
   *tool-calling* per endpoint, and record `response_metadata.model_name` (cost keying differs
   from endpoint name; date suffixes are load-bearing).
2. **Pricing maps for every endpoint you will report USD on.** Unpriced endpoints return $0 by
   design — a cost study logging $0 is self-parody. Otherwise commit to **tokens as the primary
   metric** and say so.
3. **Pilot matrix: 1 task × 1 trial × every model.** Pennies. Catches per-model quirks
   (params rejected at top level, scorer/agent-convention divergence) before they cost a sweep.
4. **Pre-start a serverless SQL warehouse and pin its id** (`MLFLOW_TRACING_SQL_WAREHOUSE_ID`).
   An X-Small interactive warehouse starved a `COUNT(*)` past 50s; a 2X-Small serverless did it
   in 3.3s. A prior run sat 4 days on unbounded auto-start.
5. **Auth mode is exclusive.** Ambient `DATABRICKS_HOST`/`TOKEN` and a profile pool are mutually
   exclusive — mixing them fails 100% of trials. Pick one, unset the other.
6. **Frozen slice committed as a task-id list**, plus tags (`series`, `sweep`, `arm`, `slice`,
   `model_endpoint`) on every run. Without tags, comparison is baseline-id string parsing forever.
7. **New experiment for the series** — UC trace location binds at experiment creation and cannot
   be changed later. Create it with the `UC_*` + warehouse vars already set.
8. **Run every arm once, end to end, on one fast fixture.** An arm broken at merge produced 60
   phantom trials with 0 tokens before anyone noticed (#1294); the driver can exit 0 with
   `trials: 0` (#1295). Zero-token cells mean broken arm, not efficiency.

## Ops rules

- **Fresh token per *task* invocation.** OAuth dies at ~60 min. One token per sweep will die
  mid-run; one per segment mostly survives but still gambles. Mint per task and the window
  stops mattering.
- **Never `source` a shared env file in a sweep script.** Export every variable explicitly, then
  **read the driver banner** (`model=`, `experiment=`) after launch to confirm what it bound.
- **Concurrency 2, never 4.** If not per-task, keep segments ≤50 min.
- **Detached launch (`nohup`), liveness by process + log mtime** (`pgrep -f <driver>` plus log
  growth) — wrappers get killed externally and never print an exit line.
- **Errored trials never count as pass.** Classify errors: iteration-cap / recursion errors are
  discriminative *model* signal (kimi 6, deepseek 10, gpt 1 on the same slice); 429s are infra
  noise → rerun that model at concurrency 1 rather than letting quota stand as failure.

## Cadence, N, and slicing

**Baseline → per-change incremental → final**, same frozen slice, same instrument. Slicing is
sound because every comparison is *within-slice and paired per task* — the slice never has to
estimate the bank's absolute pass rate. Stratify by category × difficulty, include 1–2 sealed
fast fixtures as canaries, commit the ids.

- **N=1 is the default** (owner doctrine). Rerun manually only on surprises: pass flips,
  zero-token cells, new error classes. N=3 buys token confidence but not quality power — a
  5-point pass-rate regression is invisible at any N you can afford.
- **Premium control models are ~70% of a sweep's cost.** Baseline and final only.
- **Mini-loop for a new arm idea: 4 fast tasks × N=1 × one model ≈ 20 min**, arm and control in
  one process, one SQL statement to read it. Promote on median in-token ratio ≤0.8 with no
  pass-rate regression; kill otherwise.

Detail, including the runner-script template that survived the wave:
[references/campaign-playbook.md](references/campaign-playbook.md).

## Analysis: SQL over traces, not runs

Runs are **tag carriers only** (`sweep`, `arm`, `model`). Every number comes from the UC trace
tables: per-trial pass/error from the predict-span attributes, per-trace token sums from trace
metadata — so a looping, errored trial's real burn counts instead of recording 0 and rewarding
the arm that loops. Then pair per task, ratio arm/control, geo-mean across tasks, and guard
zero-token cells out of the geo-mean.

Query shape, the paired-ratio math, and the failure modes it exposes:
[references/sql-harvest.md](references/sql-harvest.md).

## Expect arms to be model-dependent

The wave's headline: the same prompt-compression arm was a clean win on one model (pass flat,
input −11% / output −20%) and a regression on another (pass −0.07, tokens *up* 15–19%). A
compressed prompt made the weaker model loop. Report per model; never publish a single
cross-model verdict for an arm. Output tokens are a first-class outcome — compression that
shrinks input often grows output.

## Evidence trail

Wave `2026-08-23-token-eff-proxy-ui`: plan, expert review, and research scan under
`.wave/research/`; final harvest, per-segment logs, and the harvest script under `.wave/evals/`
(supervisor worktree, not committed). Issues: #713 #714 #1243 #1244, harness scars #491 #493,
findings filed en route #1294 #1295.
