# Scaffold templates

Copy-paste starting files for a new experiment. The *rules* they have to satisfy live in
`SKILL.md` — this file is just the bulk.

## Makefile — the command surface

```makefile
.DEFAULT_GOAL := help

# Config via env vars — sane defaults, overridable, echoed in help
export DATABRICKS_CONFIG_PROFILE ?= DEFAULT
export EXPERIMENT_CATALOG ?= my_catalog
export EXPERIMENT_SCHEMA ?= my_experiment

.PHONY: help auth-check verify test test-infrastructure tf-init tf-plan tf-apply tf-destroy

help: ## List available targets
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'
	@echo ""
	@echo "Environment variables:"
	@echo "  DATABRICKS_CONFIG_PROFILE  CLI profile (default: DEFAULT)"
	@echo "  EXPERIMENT_CATALOG         Unity Catalog name (default: my_catalog)"
	@echo "  EXPERIMENT_SCHEMA          UC schema (default: my_experiment)"

auth-check: ## Verify Databricks (+ cloud) authentication before anything live
	databricks auth describe --profile $(DATABRICKS_CONFIG_PROFILE)
	# add cloud checks as needed: aws sts get-caller-identity, gcloud auth list, ...

verify: ## Prove auth + identities + connectivity end-to-end with real requests
	uv run python scripts/verify.py

test: ## Run no-infra tests only (unit + composition)
	uv run pytest -m "not infrastructure"

test-infrastructure: auth-check ## Run live tests (requires Databricks/cloud auth)
	uv run pytest -m infrastructure
```

Add `tf-init` / `tf-plan` / `tf-apply` / `tf-destroy` when the experiment has a
`terraform/` directory, and a scenario target per extra pytest marker
(`test-cross-region: ## ...` → `uv run pytest -m cross_region`).

Note that exporting `DATABRICKS_CONFIG_PROFILE` from here is what makes the
unified-auth trap in `fail-closed.md` possible: a profile is visible to every script,
so any client meant to be a *different* principal must pin its `auth_type` explicitly.

## pyproject.toml — uv-managed, tiered tests

```toml
[project]
name = "<experiment-name>"
version = "0.1.0"
description = "Experiment: <the question being answered>"
requires-python = ">=3.11"
dependencies = ["databricks-sdk", "requests"]

[dependency-groups]
dev = ["pytest>=8.0.0", "ruff>=0.8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"
markers = [
    "infrastructure: Tests requiring live Databricks/cloud infrastructure",
]
```

Add one marker per live scenario the matrix needs (`cross_region`, `serverless`, …),
each with its own make target.
