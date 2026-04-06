---
name: databricks-apps
description: Build and deploy Databricks Apps using the bash-over-REST starter template. Use when scaffolding, configuring, deploying, or iterating on Databricks Apps with Lakebase connectivity.
version: 1.0.0
---

# Databricks Apps Development

Build full-stack Databricks Apps using the bash-over-REST starter template. The core pattern enables fast local iteration via `uvicorn --reload` so you never wait for multi-minute redeploys during development.

## When to Use

- Scaffolding a new Databricks App
- Adding features to an existing Databricks App
- Configuring Lakebase (Postgres) connectivity
- Setting up DAB (Databricks Asset Bundles) deployment
- Debugging app deployment or authentication issues

## Reference Template

**Always start by copying the starter template into the target project directory:**

```bash
# Clone the shareables repo (shallow, sparse) and copy the template
git clone --depth 1 --filter=blob:none --sparse https://github.com/randypitcherii/shareables.git /tmp/shareables-clone
cd /tmp/shareables-clone && git sparse-checkout set databricks/randy_apps_starter
cp -r databricks/randy_apps_starter/* databricks/randy_apps_starter/.* <TARGET_PROJECT_DIR>/
rm -rf /tmp/shareables-clone
```

Source: `https://github.com/randypitcherii/shareables/tree/main/databricks/randy_apps_starter`

**This is mandatory.** Do NOT scaffold from scratch. Do NOT write app.py, app.yaml, databricks.yml, or Makefile from memory. Copy the exact template files first, then customize. The template contains battle-tested patterns (CWD tracking, session state, streaming) that are easy to get wrong.

## The Bash-over-REST Pattern

The starter template implements a REST API that wraps shell commands, enabling interactive terminal sessions over HTTP. This is the core architectural pattern — understand it before building anything.

### Why This Pattern Matters

- **Local dev is instant**: `make dev` runs uvicorn with `--reload`. Code changes trigger automatic restart — no Databricks deploy needed
- **Deploy only when ready**: Only push to Databricks when a feature is stable
- **Same API surface locally and deployed**: The app behaves identically in both environments
- **Frontend and backend iterate independently**: Vite dev server proxies `/api/*` to the local backend

### Core API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/shell/run` | POST | Execute bash commands, capture stdout/stderr/exit code |
| `/api/v1/shell/stream` | POST | Streaming shell output for long-running commands |
| `/api/v1/shell/complete` | POST | Shell tab completion |
| `/api/v1/healthcheck` | GET | Runtime freshness check |
| `/api/v1/db/health` | GET | Lakebase connectivity check |
| `/api/v1/auth/context` | GET | Forwarded user and OBO token status |

### How CWD Tracking Works

Each shell request wraps the command with a CWD marker (`__RCP_CWD_<uuid>__=`) appended after execution. The marker is stripped from output and used to persist the working directory across requests. Session state is stored in SQLite (`/tmp/randy_apps_starter_session_state.sqlite3`).

## Local Development Workflow

### Quick Start

```bash
# Clone the starter template
git clone https://github.com/randypitcherii/shareables.git
cd shareables/databricks/randy_apps_starter

# Start local dev server (hot-reload enabled)
make dev
# App available at http://127.0.0.1:8000
```

### What `make dev` Does

1. Runs `uv sync` to install dependencies
2. Kills any existing process on port 8000
3. Starts `uvicorn app:app --reload --host 127.0.0.1 --port 8000`

The `--reload` flag is the key — every code change triggers an automatic restart. Iteration is sub-second.

### Testing

```bash
make test        # Run pytest
make verify      # Run tests + validate DAB bundles
```

## Deployment

### Databricks Asset Bundles (DAB)

The template uses `databricks.yml` for deployment configuration with dev/prod targets.

```bash
# Deploy to dev (uses branch-specific Lakebase branch)
make deploy-dev

# Deploy to prod
make deploy-prod
```

### What Deployment Does

1. `databricks bundle deploy -t <target>` — pushes source to workspace
2. `databricks apps deploy <app-name> --source-code-path <path>` — deploys the app

### Dev vs Prod Targets

| Setting | Dev | Prod |
|---------|-----|------|
| Root path | `/Workspace/Users/<you>/.bundle/<name>/dev` | `/Workspace/Shared/.bundle/<name>/prod` |
| Lakebase branch | `dev-<git-branch-slug>` | `main` |
| App name | Dynamic (branch-based) | Fixed |

## app.yaml Configuration

The container runtime configuration:

```yaml
command:
  - bash
  - -lc
  - >
    uv sync --frozen &&
    uv run uvicorn app:app
    --host 0.0.0.0
    --port ${DATABRICKS_APP_PORT:-8000}
    --workers ${UVICORN_WORKERS:-2}
    --timeout-keep-alive ${UVICORN_TIMEOUT_KEEP_ALIVE:-5}
    --timeout-graceful-shutdown ${UVICORN_TIMEOUT_GRACEFUL_SHUTDOWN:-10}
    --limit-concurrency ${UVICORN_LIMIT_CONCURRENCY:-16}
    --limit-max-requests ${UVICORN_LIMIT_MAX_REQUESTS:-2000}

env:
  - name: DATABRICKS_OBO_ENABLED
    value: "true"
  - name: UVICORN_WORKERS
    value: "2"
  - name: SESSION_STATE_DB_PATH
    value: "/tmp/randy_apps_starter_session_state.sqlite3"
```

Key details:
- **uv-native launch**: `uv sync --frozen && uv run uvicorn` — no requirements.txt needed
- **uv 0.10.2** is pre-installed on the Databricks Apps runtime (Ubuntu 22.04, Python 3.10 system, 3.11 in .venv)
- `DATABRICKS_APP_PORT` is auto-injected by the platform (defaults to 8000 locally)

## Lakebase (Postgres) Connectivity

### Auto-Injected Environment Variables

When deployed to Databricks, these are automatically available:

| Variable | Value |
|----------|-------|
| `PGHOST` | Auto-set by platform |
| `PGPORT` | `5432` |
| `PGDATABASE` | `postgres` |
| `PGSSLMODE` | `require` |
| `DATABRICKS_CLIENT_ID` | Service principal client ID |
| `DATABRICKS_CLIENT_SECRET` | Service principal secret |
| `DATABRICKS_HOST` | Workspace URL |

### M2M OAuth Recipe for Lakebase

To authenticate the service principal with Lakebase Postgres:

```
user = DATABRICKS_CLIENT_ID
password = OAuth JWT from /oidc/v1/token
  (Basic auth with client_id:client_secret, grant_type=client_credentials, scope=all-apis)
```

### Critical: Schema Creation

**The service principal cannot write to the `public` schema.** You must `CREATE SCHEMA` first, then use that schema for all tables.

## Makefile Targets

| Target | Purpose |
|--------|---------|
| `make dev` | Start local dev server with hot-reload |
| `make test` | Run pytest |
| `make verify` | Run tests + validate DAB bundles |
| `make deploy-dev` | Deploy to dev target |
| `make deploy-prod` | Deploy to prod target |

## Common Mistakes

| Mistake | Why It's Wrong | Correct Approach |
|---------|----------------|------------------|
| Deploying after every change | Multi-minute redeploy cycle | Use `make dev` for local iteration |
| Using requirements.txt | Template uses uv natively | Use `pyproject.toml` + `uv sync` |
| Writing to public schema | Service principal lacks permission | `CREATE SCHEMA <name>` first |
| Hardcoding workspace URLs | Breaks across environments | Use `DATABRICKS_HOST` env var |
| Skipping `--frozen` in app.yaml | Non-reproducible installs | Always use `uv sync --frozen` in production |
| Scaffolding from scratch | Misses bash-over-REST patterns | Clone the starter template |

## Iteration Philosophy

1. **Develop locally first** — `make dev` gives sub-second feedback
2. **Test locally** — `make test` runs the full suite without deploying
3. **Deploy to dev** — only when a feature is stable enough to test in-context
4. **Deploy to prod** — only after dev validation passes

Never skip straight to deployment. The bash-over-REST pattern exists specifically to keep the inner loop fast and reliable.
