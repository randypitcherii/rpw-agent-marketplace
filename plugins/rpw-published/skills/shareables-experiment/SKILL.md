---
name: shareables-experiment
description: Use when starting, scaffolding, or structuring an experiment/evaluation in the shareables repo — "new experiment", "set up an evaluation", "scaffold an experiment folder", "structure this eval", or bringing an experiment up to house conventions. Covers Makefile command surface, tiered pytest markers, terraform/, numbered scripts + verify.py, committed results/ JSON, README findings matrix, public-repo hygiene. NOT for library/demo folders or rpw agent-runtime evals (libs/rpw_evals).
---

# Shareables Experiment Structure

House structure for an **experiment/evaluation** in the shareables repo: a folder
whose deliverable is an *answered question backed by live evidence* — not a demo,
not a library. The structure exists so results are comparable across experiments
and so nobody re-derives conventions by archaeology from prior folders.

**The ethos: settable ≠ enforcing.** An experiment's claims are only as good as
the live responses behind them. Every ✅/❌ in the findings matrix must trace to a
script that ran against real infrastructure and wrote its evidence to `results/`.
If a capability could not be isolated, the cell is ❓ with a note explaining why —
never asserted either way.

## When to Use

- Starting a new experiment/evaluation in `shareables/experiments/`
- Bringing an existing experiment folder up to house structure
- Deciding where a new script, result artifact, or findings doc belongs
- Reviewing an experiment PR for structural conventions

**Not for:** `shareables/databricks/libraries/` or `demos/` folders (they ship a
product — though `hive_to_delta` shows how an experiment graduates into one), or
agent-runtime evals (`libs/rpw_evals` in the rpw monorepo).

## The scaffold

```
experiments/<experiment_name>/
├── Makefile                    # THE command surface — default target is help
├── README.md                   # overview + findings matrix (the deliverable)
├── pyproject.toml              # uv-managed; tiered pytest markers
├── .env.example                # committed; every var commented, placeholders only
├── .gitignore                  # .env, .venv, terraform state, caches
├── scripts/
│   ├── README.md               # what each script does, prerequisites, scenarios
│   ├── _common.py              # shared helpers: auth, output style, results writing
│   ├── verify.py               # prove auth + connectivity end-to-end with ONE real call
│   └── <topic>/                # numbered scripts, one per matrix row
│       ├── _<topic>_common.py
│       ├── 01_<first_question>.py
│       └── 02_<second_question>.py
├── results/
│   ├── .gitkeep
│   └── matrix_results.json     # machine-readable outcomes — COMMITTED
├── terraform/                  # only if the experiment needs cloud infra
│   ├── README.md
│   ├── main.tf / variables.tf / outputs.tf
│   ├── terraform.tfvars.example
│   └── .gitignore              # state, .terraform/, terraform.tfvars
├── tests/                      # only if the experiment has enough code to test
│   └── conftest.py + test_*.py
└── docs/
    ├── research/               # findings write-ups (referenced from the README)
    └── plans/                  # dated design docs (YYYY-MM-DD-<topic>.md)
```

Omit directories the experiment doesn't need (no infra → no `terraform/`; scripts
only → no `tests/`). Never omit the Makefile, README matrix, or `results/`.

## Makefile — the command surface

Every interaction goes through `make`. Someone who clones the repo should be able
to run `make` (bare) and see everything the experiment can do. Copy-paste starting
file: [`templates.md`](templates.md).

Rules:

- **`help` is the default goal** and self-documents via `## ` comments — never a
  hand-maintained echo block that drifts from the real targets.
- **`auth-check` before anything live.** It verifies every auth surface the
  experiment touches (Databricks profile, AWS/GCP/Azure identity) and live
  targets depend on it.
- **Config is env vars with `?=` defaults**, exported so scripts inherit them,
  and every one is echoed in `help` with its default.
- **`verify` proves the stack end-to-end with one real call** before any matrix
  work — an HTTP 200 (or equivalent), not a config check — and proves *which
  identity* made it (below).

## Fail closed on identity and probes

The dangerous failure is not a crash — it is a matrix that measures the wrong
thing and looks right. All three of these produced believable, wrong rows in a
live delegated-privilege experiment (`shareables#46`). The harness must refuse to
record results until each is settled:

- **Prove identities are distinct.** Every principal calls an identity endpoint
  (`w.current_user.me()`, `SELECT current_user()`); the harness asserts the
  expected values and **writes nothing to `results/`** if two supposedly distinct
  principals resolve to the same identity. Record the identity per row.
- **Pin the auth method.** With more than one credential source present, an SDK
  client built from explicit `client_id`/`client_secret` still loses to a
  configured `DATABRICKS_CONFIG_PROFILE` unless it sets `auth_type="oauth-m2m"`.
- **Reachability ≠ authorization.** Any HTTP response proves the route completed.
  `401`/`403` are authorization findings, recorded with their status code — never
  scored as connectivity failures. No `raise_for_status()` inside a probe.
- **Never infer credentials from a name.** Allowlist credential-bearing keys, or
  prove auth with a real request. A `DATABRICKS_*` prefix scan matches
  `DATABRICKS_ROOT_VIRTUALENV_ENV`, a virtualenv path.

Full write-up of the three traps, `_common.py` / `verify.py` helper shapes, and the
review checklist: [`fail-closed.md`](fail-closed.md).

## pyproject.toml — uv-managed, tiered tests

The experiment is a uv project (see the **python-with-uv** skill for env/deps
mechanics — always `uv run`, never bare `python3` or pip). Starting file:
[`templates.md`](templates.md). The pytest contract is two tiers, two make targets:

- **No-infra tests** (unit + composition with mocks): the default, run by
  `make test` with `-m "not infrastructure"`. Anyone can run these with zero
  credentials.
- **`infrastructure`-marked tests**: hit live Databricks/cloud, run by
  `make test-infrastructure`, gated behind `auth-check`. Add scenario markers
  (e.g. `cross_region`) with their own targets when the matrix calls for them.

Whether `uv.lock` is committed follows the *shareables repo's* convention (it
commits locks for reproducibility) — not the rpw monorepo's gitignore rule,
which exists for registry-proxy reasons specific to that repo.

## scripts/ — numbered evidence generators

- **One numbered script per matrix row** (`01_...py`, `02_...py`), named after
  the question it answers, grouped in a topic subdirectory when there are many.
  The number ties script → matrix row → results entry.
- **`_common.py`** holds shared helpers: auth/token acquisition, host
  resolution, section/ok/fail output helpers, and the writer for
  `results/matrix_results.json` — which refuses to write on an unproven or
  collided identity. Scripts stay thin and readable.
- **`verify.py`** is the end-to-end auth proof `make verify` runs. It makes one
  real request per principal, asserts their identities are distinct, and prints
  exactly what worked (route, identity, status code).
- **`scripts/README.md`** documents prerequisites, what each script does, and
  the scenarios it sets up. Failure output is data: print rejected-route bodies
  and error shapes — *which* thing failed and *how* is often the finding.
- Scripts must be idempotent or clean up after themselves (test principals,
  temp tables) so a matrix row can be re-run for reproduction.

## results/ — committed evidence

Machine-readable outcomes are **committed**, not gitignored. The canonical
artifact is `results/matrix_results.json`: one entry per matrix row with the
row id, status, timestamp, and the measured evidence (status codes, counts,
error identifiers). Scripts write it through the shared helper in `_common.py`
so entries stay uniform. The README matrix and this file must agree — the JSON
is the source of truth; the matrix is its readable projection.

## README — the findings matrix is the deliverable

The README leads with the question and lands on a **results matrix**:

```markdown
| # | Capability / Question | Claim / Source | Result | Notes |
|---|---|---|---|---|
| 1 | <what was tested> | <doc link or claim origin> | ✅ | <measured evidence> |
| 2 | <...> | <...> | ❌ | <what actually happened> |
| 3 | <...> | <...> | ❓ | <why it couldn't be isolated> |
```

- **Status vocabulary:** ✅ works as claimed · ❌ does not (with evidence) ·
  ◑ partially · ❓ could not be isolated (say why — "the script didn't run" is
  never the reason).
- Every row cites its source (docs link, announcement, field observation) and
  its evidence (script + results entry).
- Date-stamp the test run and name the environment shape ("one real AWS
  workspace, Preview X not enrolled") — results are claims about a moment.
- Longer analysis goes in **Key Findings** sections under the matrix, and deep
  write-ups in `docs/research/`; design docs in `docs/plans/` are dated.

## terraform/ — infra as code, state never committed

When the experiment needs cloud infrastructure:

- `terraform.tfvars.example` is committed with placeholder values;
  `terraform.tfvars` is gitignored.
- `terraform/.gitignore` covers `*.tfstate*`, `.terraform/`, `terraform.tfvars`.
- `tf-init` / `tf-plan` / `tf-apply` / `tf-destroy` make targets wrap the
  lifecycle; `terraform/README.md` says what gets created and what it costs.
- Tear-downable by design: the experiment ends with `make tf-destroy`, not an
  orphaned sandbox.

## Public-repo hygiene

The shareables repo is public. In every committed artifact — code, results
JSON, docs, tfvars examples:

- **Placeholders only** for hosts, account ids, emails, bucket names
  (`https://my-workspace.cloud.databricks.com`, `my_catalog`). Real coordinates
  live in `.env` / `terraform.tfvars`, both gitignored, with committed
  `.example` twins (the **env-preferences** skill covers the env-file pattern).
- **No customer-identifying data** in results artifacts, research docs, or
  script output committed to `results/` — scrub before committing.
- **No PATs, no secrets** — SSO/OAuth profiles only; helpers should refuse
  `dapi` tokens on sight.

## Composes with

- **python-with-uv** — env/deps mechanics; this skill only fixes the pytest
  marker tiers and make-target mapping.
- **databricks-jobs** — if the experiment schedules jobs: DABs-defined,
  profile auth, CLI log debugging. Don't hand-roll job wiring here.
- **env-preferences** — the `.env.example` / gitignored-`.env` pattern.

## Exemplars

- [`experiments/coding_agent_inference_unity_ai_gateway`](https://github.com/randypitcherii/shareables/tree/main/experiments/coding_agent_inference_unity_ai_gateway) — the purest
  expression: findings matrix, numbered governance scripts, `verify.py`,
  committed `matrix_results.json`, SSO-only helpers.
- [`databricks/libraries/hive_to_delta`](https://github.com/randypitcherii/shareables/tree/main/databricks/libraries/hive_to_delta) — started as an experiment,
  graduated to a library: tiered test targets, env-var config echoed in help,
  `terraform/` with `tfvars.example`, `scripts/README.md`.
