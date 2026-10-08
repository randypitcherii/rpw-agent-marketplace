# Destructive run-operations — the `dry_run` contract in full

Companion to `SKILL.md`'s "Destructive run-operations" section, which carries the rule
itself. This file holds the full reference macro, the guardrails, and the CI wiring.

## The rule

Every dbt run-operation macro that **drops, deletes, or rewrites** anything takes
`dry_run` as its **final argument**, defaulting to `true`. A dry run prints the exact
statements a live run would execute — nothing more, nothing less, no partial side effects.
Automation that means it passes `dry_run: False` explicitly.

Why it is worth being strict about: you can always ask "what WOULD this do?" against live
state at zero risk, and a half-remembered CLI invocation can never destroy anything. The
default is the safe answer, so forgetting an argument fails safe rather than fails
destructive.

Three properties make it work, and all three are load-bearing:

1. **Final position.** Destructive macros grow arguments over time; keeping `dry_run` last
   means every existing positional or `--args` invocation keeps its meaning, and the flag
   is always in the same place across the whole project.
2. **Default `true`.** A missing argument prints instead of destroying.
3. **Same statements, both paths.** The statement list is built once and then either logged
   or executed. If the dry run computed a different set than the live run, the preview
   would be a lie — this is why you never write two branches that each build their own SQL.

## Reference implementation

`ci_cleanup` — end-of-run CI hygiene in one operation: drop this build's ephemeral schema,
then sweep stale CI schemas leaked by earlier failed or cancelled runs.

```sql
-- macros/operations/ci_cleanup.sql
{% macro ci_cleanup(schema, prefix='my_project_pr', older_than_days=3, catalog=none, dry_run=true) %}
  {%- if not schema -%}
    {{ exceptions.raise_compiler_error('ci_cleanup requires the current build `schema`.') }}
  {%- endif -%}
  {#- The prefix must BE the CI marker: base schema + '_pr', letters/digits/underscores
      only. A looser prefix is how a sweep reaches a dev schema, and a prefix carrying
      regex or quote characters is how it reaches everything else. -#}
  {%- if not prefix or not modules.re.match('^[a-z0-9_]+_pr$', prefix) -%}
    {{ exceptions.raise_compiler_error("ci_cleanup requires a `prefix` matching ^[a-z0-9_]+_pr$ -- the base schema plus the CI 'pr' marker (e.g. my_project_pr).") }}
  {%- endif -%}
  {%- set catalog = catalog or target.catalog -%}

  {%- set statements = [] -%}
  {%- do statements.append('drop schema if exists ' ~ adapter.quote(catalog) ~ '.' ~ adapter.quote(schema) ~ ' cascade') -%}

  {#- Anchored regex, NEVER `like '<prefix>%'`. Two reasons, both bit us:
      1. `_` is a single-character wildcard in LIKE, so 'my_project_pr%' also matches
         my-project-priya-shaped names the pattern never mentions.
      2. `%` has no right anchor, so every schema that merely STARTS with the prefix
         matches -- including a dev schema owned by a human whose $USER starts with 'pr'.
      '^<prefix>[0-9]+$' matches exactly <base>_pr<PR_NUMBER> and nothing else. -#}
  {%- set stale = run_query(
        'select schema_name from ' ~ adapter.quote(catalog) ~ '.information_schema.schemata'
        ~ " where schema_name rlike '^" ~ prefix ~ "[0-9]+$'"
        ~ " and schema_name != '" ~ schema ~ "'"
        ~ ' and created < current_timestamp() - interval ' ~ older_than_days ~ ' days'
      ) -%}
  {%- for row in stale.rows -%}
    {%- do statements.append('drop schema if exists ' ~ adapter.quote(catalog) ~ '.' ~ adapter.quote(row[0]) ~ ' cascade') -%}
  {%- endfor -%}

  {%- for statement in statements -%}
    {%- if dry_run -%}
      {{ log('DRY RUN (pass dry_run: False to execute): ' ~ statement, info=True) }}
    {%- else -%}
      {{ log('Executing: ' ~ statement, info=True) }}
      {%- do run_query(statement) -%}
    {%- endif -%}
  {%- endfor -%}
  {{ log('ci_cleanup: ' ~ statements | length ~ ' statement(s), dry_run=' ~ dry_run, info=True) }}
{% endmacro %}
```

Three guardrails beyond `dry_run`, all worth copying:

- **Anchored match, not prefix `LIKE`.** `^<prefix>[0-9]+$` matches exactly the schemas CI
  builds. `like '<prefix>%'` matches every schema that starts with the prefix — and because
  `_` is a single-character wildcard in `LIKE`, it matches more names than the pattern
  literally reads. Rejecting a *shape* of match is a stronger guardrail than validating an
  argument, because it holds no matter what the caller passes.
- **Validated `prefix`, not merely non-empty.** The old check rejected the empty prefix — the
  wrong failure mode. Nothing stopped an over-broad one, which is the failure that costs a
  schema. `^[a-z0-9_]+_pr$` forces the prefix to be the base schema plus the CI marker, and
  keeps regex and quote characters out of a string that is interpolated into SQL.
- **Compiler errors, not silent no-ops**, for missing or malformed required arguments — an
  `exceptions.raise_compiler_error` is visible in CI logs; a skipped statement is not.

## Invoking it

```bash
# see what would happen (the default — no arguments needed to be safe)
uv run dbt run-operation ci_cleanup \
  --args '{schema: my_project_pr42}' --target ci --profiles-dir .

# actually do it (what CI runs after a green build)
uv run dbt run-operation ci_cleanup \
  --args '{schema: my_project_pr42, dry_run: False}' --target ci --profiles-dir .
```

The live invocation belongs in the CI job's cleanup step, keyed to the same
`_pr<PR_NUMBER>`-suffixed schema the run built — [this skill's `SKILL.md`](SKILL.md) One True Way
table for a dbt-built schema, the **`dabs-environments`** skill's test target for a
bundle-deployed one. Both carry the `pr` marker precisely so this sweep can anchor on it; that
contract is stated once, in `SKILL.md`'s One True Way section.

## What the sweep actually guarantees, and what it does not

Be precise about this, because a false guarantee is what a reader trusts instead of
re-deriving the match. This section used to assert the sweep "can only ever reach CI-owned
schemas — never dev's `*_<user>` schemas." That was wrong: with a prefix `LIKE`,
`my_project_pr%` matches `my_project_priya`, and the macro emitted
`drop schema if exists main.my_project_priya cascade` (#1026). Dev, CI, and prod all live in
the same `DBT_CATALOG`, so the pattern is the *only* thing separating them.

**What is true of the anchored pattern:** `^<base>_pr[0-9]+$` matches only the base schema,
then `_pr`, then digits to the end of the name. A dev schema is `<base>_<user>`, so it is in
the match set only if `$USER` is literally `pr` followed by digits — `priya` is not (`iya`
is not digits), and neither is any ordinary username. Prod's bare `<base>` carries no suffix
at all. If your org can mint a `pr42`-shaped username, the pattern alone is not enough.

**What the pattern does not give you: authority.** In Unity Catalog `DROP SCHEMA` requires
ownership of the schema or `MANAGE` on it (or an ancestor). So the sweep's blast radius is
`pattern ∩ what the CI principal may drop`:

| CI service principal holds | A stray match becomes |
|---|---|
| `USE CATALOG` + `CREATE SCHEMA` only (recommended) | `PERMISSION_DENIED` — the run fails loudly, nothing is dropped |
| Ownership of / `MANAGE` on the catalog (common when CI provisions its own schemas) | An executed `drop schema ... cascade` on someone else's data |

Grant CI the narrow posture, and the pattern and the grant model each independently prevent
the accident. Under the broad posture the pattern is the only thing left, so it must be
exactly right — which is the argument for an anchored match over a `LIKE`, and for
`dry_run` staying the default.

Isolating environments by **catalog** rather than by schema suffix removes the shared blast
radius entirely and is worth it wherever your Databricks setup allows it. This skill's
`profiles.yml` shares one catalog because that is the common case, not because it is safer.

## Reviewing someone else's destructive macro

| Look for | Why it matters |
|---|---|
| `dry_run` absent | No way to preview; the macro is one typo from data loss |
| `dry_run` not last | Position drifts between macros; `--args` invocations silently change meaning |
| `dry_run=false` default | Forgetting the argument destroys instead of printing |
| Dry-run branch builds its own SQL | The preview can diverge from what a live run does |
| Dry run also writes (temp tables, "harmless" DDL) | "Prints nothing more" is the contract; partial side effects break it |
| Sweep matched with `like '<prefix>%'` | No right anchor, and `_` is a LIKE wildcard — it reaches names the pattern never mentions, including dev's (#1026) |
| Sweep pattern with no environment marker | `_42` and `_priya` are the same shape; nothing distinguishes CI's schemas from a human's |
| Prefix validated only as non-empty | Guards the wrong failure — an over-broad prefix is the one that costs a schema |
| "It can only reach CI schemas" asserted, not derived | A false guarantee is worse than none: the reader trusts it instead of re-deriving the match |
