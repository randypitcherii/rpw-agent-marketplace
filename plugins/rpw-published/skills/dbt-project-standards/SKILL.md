---
name: dbt-project-standards
description: dbt-on-Databricks house standards — One True Way env isolation (user-suffixed dev schema, PR-suffixed CI, bare prod), staging/intermediate/marts layering, profile-only auth (no PATs), uv-managed dbt, and dry_run-last on destructive run-operations. Use when you set up or review a dbt project, configure "dbt environments", run "dbt on Databricks", write profiles.yml / dbt_project.yml / generate_schema_name, or write a dbt macro that drops or deletes anything.
---

# dbt Project Standards

The standard dbt project setup for Databricks. There is **one golden path per concern**:
one env-isolation scheme, one layering scheme, one auth model, one way to install dbt.
Environment isolation is the "One True Way" pattern — same base name + env-derived suffix —
the same philosophy the **`dabs-environments`** skill applies to Databricks Asset Bundles.
The two skills should read as one philosophy applied to two tools.

## When to Use

- Setting up a new dbt project or reviewing an existing one for conformance
- Configuring dbt environments (dev / CI / prod targets in `profiles.yml`)
- Running dbt against Databricks (adapter config, auth, catalog/schema wiring)
- Deciding where a model lives (staging vs intermediate vs marts) or what to name it

## One True Way env isolation

Same table as the DABs skill, dbt-side:

| Concern | dev | CI (test) | prod |
|---|---|---|---|
| Schema | `<base_schema>_<user>` | `<base_schema>_pr<pr_number>` | `<base_schema>` (unchanged) |
| Identity | Human, OAuth U2M (browser SSO) | Service principal, OAuth M2M (CI-injected) | Service principal, OAuth M2M |
| Selected by | `target: dev` (default) | `--target ci` + CI env vars | `--target prod` |

Two pieces implement it:

### 1. `profiles.yml` — the env suffix lives in `target.schema`

```yaml
# profiles.yml (committed — it contains no secrets; identity comes from the environment)
my_project:
  target: dev
  outputs:
    dev:
      type: databricks
      catalog: "{{ env_var('DBT_CATALOG', 'main') }}"
      schema: "{{ env_var('DBT_BASE_SCHEMA', 'my_project') }}_{{ env_var('USER') }}"
      host: "{{ env_var('DATABRICKS_HOST') }}"
      http_path: "{{ env_var('DBT_HTTP_PATH') }}"
      auth_type: oauth          # OAuth U2M — browser SSO, no token on disk
    ci:
      type: databricks
      catalog: "{{ env_var('DBT_CATALOG', 'main') }}"
      schema: "{{ env_var('DBT_BASE_SCHEMA', 'my_project') }}_pr{{ env_var('PR_NUMBER') }}"
      host: "{{ env_var('DATABRICKS_HOST') }}"
      http_path: "{{ env_var('DBT_HTTP_PATH') }}"
      auth_type: oauth          # OAuth M2M — picks up SP client id/secret from env
      client_id: "{{ env_var('DATABRICKS_CLIENT_ID') }}"
      client_secret: "{{ env_var('DATABRICKS_CLIENT_SECRET') }}"
    prod:
      type: databricks
      catalog: "{{ env_var('DBT_CATALOG', 'main') }}"
      schema: "{{ env_var('DBT_BASE_SCHEMA', 'my_project') }}"
      host: "{{ env_var('DATABRICKS_HOST') }}"
      http_path: "{{ env_var('DBT_HTTP_PATH') }}"
      auth_type: oauth
      client_id: "{{ env_var('DATABRICKS_CLIENT_ID') }}"
      client_secret: "{{ env_var('DATABRICKS_CLIENT_SECRET') }}"
```

<!-- TODO: confirm against canonical project — whether dev reuses the `~/.databrickscfg`
CLI profile (unified/SDK auth in newer dbt-databricks) instead of `auth_type: oauth`
browser SSO, and the exact adapter fields that select it. The no-PAT rule is firm either
way; only the dev-side mechanism needs confirming. -->

### 2. `generate_schema_name` — custom schemas extend, never replace

dbt's default `generate_schema_name` puts custom-schema models in
`<target.schema>_<custom_schema>`. Keep that concatenating behavior — it is what makes the
env suffix compose with layer schemas — but pin it explicitly so nobody swaps in the
"custom name wins" variant that would break isolation:

```sql
-- macros/generate_schema_name.sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- set default_schema = target.schema -%}
    {%- if custom_schema_name is none -%}
        {{ default_schema }}
    {%- else -%}
        {{ default_schema }}_{{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
```

The invariant: **every relation a run writes carries the run's env suffix.** A dev run can
only ever write to `*_<user>` schemas; a CI run to `*_pr<pr_number>`; parallel PRs and
parallel humans never collide, and prod is only reachable through the prod target.

The literal `pr` in the CI suffix is load-bearing, not decoration: it is the only marker a
cleanup sweep can match on that a human's `$USER` cannot collide with. Without it, `_42` and
`_priya` are the same shape, and any pattern broad enough to find CI's schemas also finds
dev's (#1026). **This reasoning lives here and is deliberately not repeated:** the
**`dabs-environments`** test target carries the same marker for the same reason (#1041), and
changing either side without the other leaves PR schemas no sweep can reach.

<!-- TODO: confirm against canonical project — whether the canonical macro is exactly the
concatenating default (as above) or adds project-specific behavior (e.g. prod-only bare
custom schemas). -->

## Destructive run-operations — `dry_run` is the final argument

Part of the One True Way, not an optional nicety: **every run-operation macro that drops,
deletes, or rewrites anything takes `dry_run` as its final argument, defaulting to `true`.**
A dry run prints the exact statements a live run would execute — nothing more. Automation
that means it passes `dry_run: False` explicitly:

```bash
uv run dbt run-operation drop_pr_schema --args '{schema: my_project_pr42}'                 # prints
uv run dbt run-operation drop_pr_schema --args '{schema: my_project_pr42, dry_run: False}' # executes
```

Build the statement list once, then log it or run it — never two branches that each build
their own SQL, or the preview stops matching the live run:

```sql
-- macros/operations/drop_pr_schema.sql
{% macro drop_pr_schema(schema, catalog=none, dry_run=true) %}
  {%- if not schema -%}
    {{ exceptions.raise_compiler_error('drop_pr_schema requires `schema`.') }}
  {%- endif -%}
  {%- set catalog = catalog or target.catalog -%}
  {%- set statements = ['drop schema if exists ' ~ adapter.quote(catalog) ~ '.' ~ adapter.quote(schema) ~ ' cascade'] -%}
  {%- for statement in statements -%}
    {%- if dry_run -%}
      {{ log('DRY RUN (pass dry_run: False to execute): ' ~ statement, info=True) }}
    {%- else -%}
      {{ log('Executing: ' ~ statement, info=True) }}
      {%- do run_query(statement) -%}
    {%- endif -%}
  {%- endfor -%}
{% endmacro %}
```

Why it is strict: you can always ask "what WOULD this do?" against live state at zero risk,
and no half-remembered CLI invocation can destroy anything — the default is the safe answer.
The full contract, the `ci_cleanup` reference macro (stale-schema sweep matched on an
**anchored** pattern, never a prefix `LIKE`), CI wiring, the grant posture the sweep's safety
depends on, and a review checklist live in
[`destructive-operations.md`](destructive-operations.md).

## Project structure — staging / intermediate / marts

```
models/
  staging/          # 1:1 with source tables; rename, cast, light cleanup ONLY
    <source>/
      _<source>__sources.yml
      stg_<source>__<entity>.sql
  intermediate/     # reusable joins/pivots that aren't end products
    int_<entity>_<verb>.sql
  marts/            # what consumers query
    <domain>/
      fct_<event>.sql
      dim_<entity>.sql
```

- **staging**: one model per source table, named `stg_<source>__<entity>`, materialized as
  views. No joins, no business logic.
- **intermediate**: `int_` prefix, never exposed to consumers.
- **marts**: `fct_` / `dim_` prefix, materialized as tables, organized by domain. This is the
  only layer downstream tools query.

Sources are declared per source system in `_<source>__sources.yml`; models `ref()` staging,
never `source()` outside the staging layer.

## Auth — profile-only, no PATs (non-negotiable)

Same golden path as the **`dabs-environments`** skill, restated for dbt:

- **dev (humans):** OAuth U2M browser SSO. No token in `profiles.yml`, no token in env files.
- **CI and prod (machines):** service-principal OAuth M2M — `DATABRICKS_CLIENT_ID` +
  `DATABRICKS_CLIENT_SECRET` (+ `DATABRICKS_HOST`) injected by CI, never written to disk.
- **No PATs anywhere.** No `token:` key in any output, no `DATABRICKS_TOKEN` in any env file.
  If a dbt-Databricks guide shows `token:`, do not follow it.

Code and models never branch on auth type — the *target + environment* decide identity.

## Local dev workflow — uv-managed dbt

dbt is a project dependency managed by `uv` (the **`python-with-uv`** skill owns the general
workflow — no pip, no manual venvs):

```bash
uv add dbt-databricks && uv sync
uv run dbt deps
uv run dbt build            # dev target by default
uv run dbt build --target ci
```

Non-secret connection settings follow the **`env-preferences`** pattern: commit
`template.env` (with `DBT_CATALOG`, `DBT_BASE_SCHEMA`, `DBT_HTTP_PATH`, `DATABRICKS_HOST`
placeholders), keep real `dev.env`/`test.env`/`prod.env` local-only, select with `APP_ENV`.

<!-- TODO: confirm against canonical project — the canonical template.env variable names
(DBT_CATALOG / DBT_BASE_SCHEMA / DBT_HTTP_PATH as used above) and whether profiles.yml is
committed at the repo root or under a profiles/ dir selected with --profiles-dir. -->

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Dev run wrote to a bare (unsuffixed) schema | `generate_schema_name` overridden with "custom name wins" variant | Restore the concatenating macro above |
| Two PRs' CI runs clobber each other | CI target schema missing the PR suffix | Suffix `target.schema` with `_pr` + `PR_NUMBER` as in `profiles.yml` above |
| A cleanup sweep dropped a dev schema | CI schemas carry no `pr` marker, so the sweep pattern also matched `*_<user>` | Restore the `_pr<pr_number>` CI suffix and match it anchored (`destructive-operations.md`) |
| `token` auth errors or PAT rotation pain | Someone added `token:` to an output | Remove it; use OAuth U2M (dev) / M2M (machines) |
| Works locally, fails in CI with auth error | CI missing SP env vars | Inject `DATABRICKS_CLIENT_ID`/`SECRET`/`HOST` in the CI environment |
| A cleanup macro dropped more than intended | No `dry_run`, or it defaults to false | Add `dry_run=true` as the final argument; require a non-empty sweep prefix |

## Related skills

- **`dabs-environments`** — the same One True Way env isolation applied to Databricks Asset
  Bundles; read the two together. A dbt task scheduled as a Databricks job lives inside that
  bundle structure (see **`databricks-jobs`**).
- **`python-with-uv`** — the uv workflow `uv add dbt-databricks` / `uv run dbt` follows.
- **`env-preferences`** — the committed-template / local-only env file convention.
- **`databricks-jobs`** — scheduling `dbt` tasks as DABs-defined Databricks jobs.
