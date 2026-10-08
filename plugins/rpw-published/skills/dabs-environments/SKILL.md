---
name: dabs-environments
description: The house dev/test/prod target structure for Databricks Asset Bundles — base_catalog/base_schema variables, user-suffixed dev / PR-suffixed test / bare prod schemas, presets.name_prefix, split root_path, profile-only auth (no PATs). Use when creating or reviewing a `databricks.yml`, adding targets, or wiring bundle auth. Trigger on "set up a DAB", "databricks.yml targets", "DABs environments", "bundle dev/test/prod", "deploy this bundle".
---

# DABs Environments

The standard Databricks Asset Bundle target structure. There is **one golden path**: three
targets (`dev`, `test`, `prod`) that share one set of resources and differ only in schema
suffix, name prefix, deploy path, and mode. Environment isolation happens at the **schema
level** — same base name + env-derived suffix. This is the DABs application of the same
"One True Way" env-isolation philosophy the **`dbt-project-standards`** skill applies to dbt.

## When to Use

- Creating a new `databricks.yml` or adding targets to an existing one
- Deciding how dev/test/prod deployments of one bundle stay isolated
- Wiring bundle auth (it is profile-only — see below)
- Reviewing a bundle for conformance to house standards

## The pattern in one table

| Concern | dev | test (CI) | prod |
|---|---|---|---|
| Schema | `${var.base_schema}_${workspace.current_user.short_name}` | `${var.base_schema}_pr${var.pr_number}` | `${var.base_schema}` (unchanged) |
| `mode` | `development` | `development` (deliberate — see below) | `production` |
| `presets.name_prefix` | `[DEV - <user>] ` | `[TEST - <user>] ` | `[PROD 🏋️] ` |
| `root_path` | `/Users/<user>/.bundles/<bundle>` | `/Users/<user>/.bundles/<bundle>/pr<pr_number>` | `/Workspace/deployments/<bundle>` |
| Identity | Human via CLI profile (OAuth U2M) | Service principal (OAuth M2M, CI-injected) | Service principal (OAuth M2M) |
| Default target | ✅ | — | — |

**The `pr` in the test schema is a contract, not decoration.** CI cleanup sweeps stale PR
schemas with an **anchored** `^<base>_pr[0-9]+$` match, and refuses outright any prefix that is
not `<base>_pr`. A marker-less `${var.base_schema}_${var.pr_number}` is therefore unreachable
both ways — no sweep pattern matches it, and the prefix needed to sweep it is rejected before
one runs — so every PR's schema orphans in the catalog forever. Why the literal `pr` is the only
marker a sweep can safely key on is stated once, in the **`dbt-project-standards`** skill's
[One True Way section](../dbt-project-standards/SKILL.md); the sweep itself, its guardrails, and
the grant posture its safety depends on are in that skill's
[`destructive-operations.md`](../dbt-project-standards/destructive-operations.md).

**Why `mode: development` on test:** deliberate. Development mode deploys schedules/triggers
paused; `mode: production` is the only mode that leaves them on. A CI test deployment must
never start firing schedules, so test stays in development mode even though it runs in CI.

## Canonical `databricks.yml`

```yaml
bundle:
  name: my_bundle

variables:
  base_catalog:
    description: Catalog every target deploys into.
    default: main
  base_schema:
    description: Base schema name. Targets derive their env-isolated schema from this.
    default: my_bundle
  pr_number:
    description: PR number, injected by CI for the test target (--var="pr_number=123"). Digits only; the pr marker lives in the schema string, not in this value.
    default: "0"
  default_catalog:
    description: Resolved catalog for the active target. Resources reference this.
    default: ${var.base_catalog}
  default_schema:
    description: Resolved, env-isolated schema for the active target. Resources reference this.
    default: ${var.base_schema}

# resources reference ${var.default_catalog} / ${var.default_schema} — never a target-specific
# schema directly. The job/pipeline definitions themselves belong to the databricks-jobs skill.

targets:
  dev:
    default: true
    mode: development
    variables:
      default_schema: ${var.base_schema}_${workspace.current_user.short_name}
    presets:
      name_prefix: "[DEV - ${workspace.current_user.short_name}] "
    workspace:
      profile: DEFAULT
      root_path: /Users/${workspace.current_user.userName}/.bundles/${bundle.name}

  test:
    # development mode on purpose: keeps schedules paused. Only prod leaves them on.
    mode: development
    variables:
      default_schema: ${var.base_schema}_pr${var.pr_number}
    presets:
      name_prefix: "[TEST - ${workspace.current_user.short_name}] "
    workspace:
      root_path: /Users/${workspace.current_user.userName}/.bundles/${bundle.name}/pr${var.pr_number}

  prod:
    mode: production
    presets:
      name_prefix: "[PROD 🏋️] "
    workspace:
      root_path: /Workspace/deployments/${bundle.name}
```

Key opinions baked in:

- **Resources see only `${var.default_catalog}` / `${var.default_schema}`.** Targets override
  the variables; resources never hardcode an env-specific schema. Adding an environment never
  touches a resource definition.
- **dev is the default target** — `databricks bundle deploy` with no `--target` lands in your
  own user-suffixed sandbox, never anywhere shared.
- **test's `root_path` ends in `pr` + the PR number** so parallel PRs deploy side by side
  without clobbering each other. (The historical reference bundle had a malformed trailing
  `${}` here; the correct placeholder is `pr${var.pr_number}`, as above.) The marker is
  *load-bearing* in the schema — that string is what the cleanup sweep matches — and carried
  into the path so the target has one shape to remember and a bare `42` path segment is never
  ambiguous about what it is.
- **`presets.name_prefix` on every target** so any resource seen in the workspace UI announces
  which environment (and whose sandbox) it belongs to at a glance.

## Deploy commands

```bash
databricks bundle validate --profile DEFAULT
databricks bundle deploy   --profile DEFAULT                 # dev (default target)
databricks bundle deploy   --target test --var="pr_number=${PR_NUMBER}"   # CI only
databricks bundle deploy   --target prod                     # CI/CD only
```

## Auth golden path — exactly one model per environment, no PATs

PATs are **not supported anywhere**. No `DATABRICKS_TOKEN`, no host/token pairs in env files
or docs. If you see PAT guidance, it's wrong.

- **dev (local humans):** user SSO via SDK-native auth — `databricks auth login` (OAuth U2M),
  selected by CLI profile. `.env.template` carries only `DATABRICKS_PROFILE=DEFAULT`. Always
  pass the profile explicitly: when multiple `~/.databrickscfg` profiles match the same host,
  bare host-based auth refuses to disambiguate and fails with
  `401: Credential was not sent or was of an unsupported type` /
  `Use --profile to specify which profile to use` (this happened during live agent
  validation — see the `databricks-model-serving` skill for the full failure class).
- **test/CI and prod (machines):** service principal OAuth M2M — `DATABRICKS_CLIENT_ID` +
  `DATABRICKS_CLIENT_SECRET` (+ `DATABRICKS_HOST`) injected by the CI system / deployment
  environment. Never written to env files on disk. Machines have no `~/.databrickscfg`, so
  the `workspace.profile` in the dev target is irrelevant to them — the SP env vars win.
- **Deployed runtime (jobs / model serving):** ambient runtime identity. There is **no CLI in
  deployed contexts** — code must rely on SDK default auth resolution, and agent deployments
  must declare their resources (Genie spaces, endpoints, UC functions) at deploy time for auth
  passthrough. "CLI auth" is a local-dev concept that does not travel into deployed code.

The unifying opinion: **code never branches on auth type.** Everything uses SDK default
credential resolution; the *environment* decides identity — profile locally, SP env vars in
CI/prod, runtime identity when deployed.

## Env files

`.env.template` is committed; real env files stay local-only (the **`env-preferences`** skill
owns this convention — follow it):

```bash
# .env.template
DATABRICKS_PROFILE=DEFAULT
```

That is the whole file for a plain bundle. No hosts, no tokens, no secrets.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `401: Credential was not sent...` / `Use --profile to specify which profile to use` | Multiple `~/.databrickscfg` profiles share the host | Pass `--profile` explicitly (or set `DATABRICKS_CONFIG_PROFILE`) |
| Schedule never fires from dev/test | `mode: development` deploys schedules paused | Expected — only prod (`mode: production`) leaves them on |
| Two PRs' test deploys clobber each other | test `root_path`/schema missing the PR suffix | Suffix both with `pr${var.pr_number}` as in the canonical template |
| PR schemas pile up in the catalog; CI's cleanup sweep never matches them | test schema is `<base>_<pr_number>` — no `pr` marker for the anchored `^<base>_pr[0-9]+$` sweep to match | Use `${var.base_schema}_pr${var.pr_number}`; sweep details in `dbt-project-standards`' `destructive-operations.md` |
| Resource lands in the bare schema from dev | Resource hardcodes a schema instead of `${var.default_schema}` | Route every resource through the `default_*` variables |

## Related skills

- **`dbt-project-standards`** — the same One True Way env isolation applied to dbt
  (`profiles.yml` + `generate_schema_name`). The two should be read as one philosophy, two tools.
- **`databricks-jobs`** — owns the `resources.jobs` definitions that live inside this bundle
  structure, plus the CLI deploy/run/debug loop.
- **`env-preferences`** — the committed-template / local-only env file convention
  `.env.template` follows.
- **`databricks-model-serving`** — the ambiguous-host-profile crash class in detail, and
  Model-Serving-first conventions for bundles that serve or call LLMs.
