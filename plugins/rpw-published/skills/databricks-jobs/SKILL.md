---
name: databricks-jobs
description: Define, deploy, run, and debug Databricks Jobs the house way — DABs-defined (never UI-created), profile-based auth only (no PATs), with CLI log reading for the local-repro debugging loop. Use when creating or editing a Databricks job, wiring a job into a Databricks Asset Bundle (`databricks.yml`), scheduling a notebook/Python/dbt task, running a job from the CLI, or debugging a failed job run (reading run output, task logs, or `run-now` results).
---

# Databricks Jobs

Define Databricks Jobs **in code** as part of a Databricks Asset Bundle (DAB), deploy them
with the `databricks` CLI, and debug failed runs by reading run output from the CLI. There is
**one golden path** here — DABs-defined, profile-based auth, CLI-driven. Jobs created by
clicking in the workspace UI are not reproducible, not reviewable, and not this skill.

## When to Use

- Authoring a new job (notebook, Python wheel, spark_python, or dbt task)
- Adding or editing a job inside an existing `databricks.yml` bundle
- Deploying and running a job from the CLI
- Debugging a failed run — reading the run state, task output, and driver logs locally
- Scheduling a job (and understanding why schedules only fire in `mode: production`)

## The golden path

```
edit databricks.yml  →  databricks bundle validate  →  databricks bundle deploy
                     →  databricks bundle run <job_key>  →  read run output from the CLI
```

Every step uses the CLI and a **named profile**. No UI. No PATs. No host/token env pairs.

### 1. Define the job in `databricks.yml`

Jobs live under `resources.jobs` in the bundle. This composes directly with the
**`dabs-environments`** skill (#240) — that skill owns the `targets:` (dev/test/prod), variables,
`presets.name_prefix`, `root_path`, and the `workspace.profile` auth wiring. This skill owns the
**job resource definition** that sits inside that bundle.

```yaml
# databricks.yml — resources section (targets/variables come from the dabs-environments skill)
resources:
  jobs:
    daily_ingest:
      name: "${var.base_name} daily ingest"
      tasks:
        - task_key: ingest
          # Prefer a wheel/Python-file task over notebooks for code that wants real
          # unit tests + local repro. Notebooks are fine for exploratory/reporting jobs.
          spark_python_task:
            python_file: ../src/ingest/main.py
          environment_key: default
        - task_key: transform
          depends_on:
            - task_key: ingest
          spark_python_task:
            python_file: ../src/transform/main.py
          environment_key: default
      # Serverless compute — no cluster JSON to maintain. Pin libraries here.
      environments:
        - environment_key: default
          spec:
            client: "2"
            dependencies:
              - ../dist/*.whl
      # Schedules only fire in `mode: production` (dev/test bundles deploy paused —
      # see the dabs-environments skill for why test deliberately uses development mode).
      schedule:
        quartz_cron_expression: "0 0 6 * * ?"
        timezone_id: UTC
        pause_status: UNPAUSED
```

Key opinions:
- **Prefer file-based tasks** (`spark_python_task` / `python_wheel_task`) over `notebook_task`
  for production code — they unit-test and repro locally. Reserve notebooks for exploratory work.
- **Serverless `environments`** over `job_clusters` unless you have a hard reason — no cluster
  spec to drift, libraries pinned declaratively.
- **Inter-task deps via `depends_on`**, not separate jobs — keep one logical pipeline in one job.

### 2. Validate, deploy, run — all profile-based

```bash
# Auth: ONE named profile, selected per command. No PATs anywhere. (See "Auth" below.)
databricks bundle validate  --profile DEFAULT
databricks bundle deploy    --profile DEFAULT --target dev
databricks bundle run daily_ingest --profile DEFAULT --target dev
```

`bundle run` blocks until the run finishes and prints the run URL + final state. That is your
deploy-and-run inner loop — no UI round-trip.

## Auth — profile only, no PATs (non-negotiable)

This is the same auth opinion the **`dabs-environments`** skill (#240) defines, restated for jobs:

- **Local dev (humans):** user SSO via OAuth U2M — `databricks auth login` — selected by a CLI
  profile in `~/.databrickscfg`. Bundles carry only `DATABRICKS_PROFILE=DEFAULT` in
  `.env.template`; real env files stay local (composes with the **`env-preferences`** skill).
- **CI/test and prod (machines):** service-principal OAuth M2M — `DATABRICKS_CLIENT_ID` +
  `DATABRICKS_CLIENT_SECRET` (+ `DATABRICKS_HOST`) injected by CI. Never written to disk.
- **Deployed runtime (the job itself):** ambient runtime identity. There is **no CLI inside a
  running job** — job code relies on SDK default auth resolution. Do not put `--profile` or
  `databricks auth` calls in job code; "CLI auth" is a local-dev concept that does not travel
  into the deployed task.

**There are no Personal Access Tokens anywhere in this skill.** No `DATABRICKS_TOKEN`, no
host/token pairs in env files, bundles, or docs. If you see PAT guidance, it's wrong.

> **Always pass `--profile` explicitly.** When two `~/.databrickscfg` profiles share the same
> host (e.g. a user profile + a service principal on one workspace — a normal config), bare
> host-based auth refuses to disambiguate and crashes with
> `Use --profile to specify which profile to use`. This is the same ambiguous-host-profile
> failure class documented in the **`databricks-model-serving`** skill (#248). Pinning
> `--profile` (or `DATABRICKS_CONFIG_PROFILE`) avoids it.

## Debugging a failed run — read logs from the CLI

The whole point of DABs-defined jobs is a tight local-repro loop. When a run fails, you read
its output from the CLI — no clicking through the workspace UI.

```bash
# 1. Run it and capture the run id (run-now returns the run id; --no-wait to not block)
run_id=$(databricks jobs run-now <job_id> --profile DEFAULT -o json | jq -r '.run_id')

# 2. Poll/fetch the full run state — task-by-task result_state + termination details
databricks jobs get-run "$run_id" --profile DEFAULT -o json \
  | jq '{state: .state, tasks: [.tasks[] | {task_key, state: .state.result_state}]}'

# 3. Pull the actual task output — stdout/stderr + the error trace for a failed task
databricks jobs get-run-output <task_run_id> --profile DEFAULT -o json \
  | jq -r '.error, .error_trace, .logs'
```

`get-run` gives you the **per-task `result_state`** (which task failed); `get-run-output` gives
you that task's **stdout/stderr/error trace** (why it failed). Read the trace, fix the code
locally, `bundle deploy` + `bundle run` again. That loop stays in your shell.

> Use the per-task `run_id` (from `get-run`'s `.tasks[].run_id`) for `get-run-output`, not the
> top-level job-run id — output is per task.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `Use --profile to specify which profile to use` | Two `~/.databrickscfg` profiles share the host | Pass `--profile <name>` (or set `DATABRICKS_CONFIG_PROFILE`). See #248 in `databricks-model-serving`. |
| Schedule never fires in dev/test | dev/test deploy in `mode: development` (paused by design) | Expected — only `mode: production` leaves schedules unpaused (see `dabs-environments`). |
| `bundle run` succeeds but code is stale | Forgot `bundle deploy` after editing | Deploy is not implicit in run — always `deploy` then `run`. |
| Library/import error only in the job | Wheel not built/pinned in `environments.spec.dependencies` | Build the wheel (`uv build`) and pin `../dist/*.whl`; redeploy. |

## Related skills (the Databricks suite)

- **`dabs-environments`** (#240) — the dev/test/prod bundle structure, variables, and
  `workspace.profile` auth wiring this skill's job resources live inside. Read it first.
- **`databricks-model-serving`** — sibling ops skill; owns the ambiguous-host-profile crash
  class (#248) in detail and the Model-Serving-first LLM convention for jobs that call an LLM.
- **`databricks-apps`** — Databricks Apps (long-running services) vs. Jobs (scheduled/triggered
  batch). Use Apps for interactive/serving workloads, Jobs for batch.
- **`databricks-uc-connections`** — when a job needs to reach an external service through a
  Unity Catalog connection.
- **`env-preferences`** — the `APP_ENV` / `*.env` convention `.env.template` composes with.
- **`python-with-uv`** — build job wheels and manage deps with `uv` (`uv build`, `uv run`).
