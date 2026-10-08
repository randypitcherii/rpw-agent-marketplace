# Campaign playbook — running the sweeps

Companion to `SKILL.md`. Everything here was validated on a live 4-model, 3-arm, 334-trial
campaign (wave `2026-08-23-token-eff`, #1244).

## 1. Pilot matrix (before any sweep)

One fast fixture, one trial, every model. Record tokens, wall clock, pass, and cost:

| model | pass@1 | in-tok | out-tok | wall | note |
|---|---|---|---|---|---|
| cheap-A | 1/1 | 50k | 1.0k | 55s | clean |
| cheap-B | 1/1 | 65k | 2.0k | 98s | first attempt died of an infra fault, not the model |
| cheap-C | 0/1 | 138k | 2.0k | 96s | agent honored a repo convention the scorer doesn't check — caveat, not a bug |
| premium control | 1/1 | 615k | 9.8k | 294s | ~$3 — premium input is ~12× the cheap models |

Two things this bought that a sweep would have paid for at 100× cost: the starved-warehouse
diagnosis, and a per-model scorer caveat that had to be footnoted on every later row.

**Read a 0/1 pilot carefully.** A model that follows the prompt's own workflow discipline into a
place the scorer doesn't look is a *scorer-scope* caveat. It hits every arm of that model
equally, so within-model arm comparisons stay valid — say so in writing before the sweep, or the
first surprising row restarts the argument.

## 2. Runner script — the shape that survived

Explicit env, no shared env file, fresh token per **task**, one log per task, tags on every run.

```bash
#!/bin/bash
set -uo pipefail
cd "<repo>/libs/rpw_evals" || exit 1

# Explicit env only. NEVER `source dev.env` (or any shared env file): it is volatile
# shared state. Mid-wave it was repointed to another experiment + another model, and six
# trials landed in the wrong experiment before anyone read the banner.
export MLFLOW_TRACKING_URI=databricks MLFLOW_REGISTRY_URI=databricks-uc
export MLFLOW_EXPERIMENT="$EXPERIMENT_PATH"
export UC_CATALOG_NAME="$UC_CATALOG" UC_SCHEMA_NAME="$UC_SCHEMA"
export UC_TABLE_PREFIX="$UC_PREFIX"
export MLFLOW_TRACING_SQL_WAREHOUSE_ID="$WAREHOUSE_ID"   # pre-started, serverless
export MODEL_ENDPOINT="$ENDPOINT" MODEL_EXTRA_PARAMS=''

one() {                       # one task = one invocation = one fresh token
  task="$1"; arm="$2"
  echo "===== ${arm}/${task} start $(date +%H:%M:%S) ====="
  export DATABRICKS_CONFIG_PROFILE="$PROFILE"
  PYTHONUNBUFFERED=1 \
    uv run --extra dev python scripts/run_task_bank_baseline.py \
      --baseline-id "${MODEL_SHORT}-${arm}-v1" \
      --tasks "$task" --arm "$arm" \
      --n-trials 1 --concurrency 2 --trial-retries 1 \
      --allow-existing-baseline-id \
      --tag series="$SERIES" --tag sweep="arm-${arm}-v1" \
      --tag slice=slice-v1 --tag model="$MODEL_SHORT" \
      > "$LOGDIR/${MODEL_SHORT}-${arm}-${task}.log" 2>&1
  echo "===== ${arm}/${task} exit=$? $(date +%H:%M:%S) ====="
}
```

Rules the template encodes:

- **Per-task invocation kills the auth problem.** OAuth lives ~60 min; forced SDK refresh from
  an agent shell hits a keychain race (#491). A per-task mint never approaches the boundary. If
  you must batch tasks, keep each segment ≤50 min and re-mint between segments.
- **`env -u <pool-var>`** — ambient host/token and a profile pool are mutually exclusive.
- **One log per task**, named for model/arm/task. Segment logs are how you reconstruct a
  fragmented sweep; a single combined log is not.
- **Tags carry the comparison cube.** The baseline id stays machine-parseable as belt-and-braces,
  but analysis filters on tags.
- Copies drift. Seven near-identical copies of this block had already diverged on concurrency and
  retries by mid-wave — an instrument difference you then have to footnote. One script,
  parameterized, or accept the footnotes.

## 3. Launch and liveness

```bash
nohup bash run-arms-<model>.sh > "$LOGDIR/wrapper-<model>.out" 2>&1 &
```

- **After launch, read the driver banner** and confirm the `model=` and `experiment=` lines match
  what you intended. This is the check that would have caught the repointed-env incident.
- **Liveness = `pgrep -f run_task_bank` + log mtime**, never "the wrapper printed an exit line."
  Wrappers die externally (SIGKILL, an accidental kill from the operator) while the driver
  children keep running orphaned — and the reverse, a wedged driver with a live wrapper.
- **Stall detection is log-growth timeout.** A trial can wedge on a filesystem/glob error inside
  the agent; kill and resume that segment rather than waiting.
- **Resume = same baseline id + `--allow-existing-baseline-id` + the remaining `--tasks`.** Trace
  SQL makes the resulting multi-run mess analyzable, so partial data is never wasted.

## 4. Cadence and spend

| Stage | Shape | Notes |
|---|---|---|
| Pilot | 1 task × 1 trial × all models | pennies; gate for everything below |
| Baseline | frozen slice (8–10 tasks) × N × cheap models | premium control at N=1 or baseline-only |
| Incremental | same slice, same instrument, per arm | cheap models only; the delta is within-model |
| Final | winning arm(s) only | get explicit spend sign-off *after* incrementals make the estimate real |

- Sequence the baseline on **one** cheap model first, check tokens/traces, then fan out. A config
  bug found after a 120-trial sweep is the expensive version of the same lesson.
- Skip arms on models you already know you won't ship — the wave skipped an entire model's arm
  cube (5h serial) with no loss to the conclusion.
- Budget wall-clock honestly: large repo tasks run 3–10 min/trial and are also the
  iteration-cap magnets. They dominate the clock and produce the least interpretable rows, which
  is exactly why the *signal* slice is fixtures and the *publishable* slice is stratified.
