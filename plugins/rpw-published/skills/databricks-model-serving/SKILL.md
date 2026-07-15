---
name: databricks-model-serving
description: Create, configure, and query Databricks Model Serving endpoints, and route every in-code LLM call through Model Serving (the `ChatDatabricks` / Model-Serving-first convention) instead of a provider SDK. Use when creating or configuring a serving endpoint, querying an endpoint, choosing how Python code should call an LLM, wiring auth passthrough for a deployed agent, or debugging the ambiguous-host-profile crash (`Use --profile to specify which profile to use` / `401 Credential was not sent`).
---

# Databricks Model Serving

Two concerns, one skill: **(1)** stand up and query a Model Serving endpoint, and **(2)** the
house convention that **every LLM call inside Python code goes through Model Serving** — not the
`anthropic`/`openai` SDK directly. One golden path per concern; profile-based auth only (no PATs).

## When to Use

- Creating or updating a serving endpoint (custom model, agent, or Foundation Model API)
- Querying an endpoint from the CLI, REST, or Python
- Deciding how Python code should call an LLM (the Model-Serving-first rule)
- Wiring auth/resource passthrough for a deployed agent endpoint
- Debugging the ambiguous-host-profile crash class (#248)

## Concern 1 — Model-Serving-first for LLM-in-code (the house convention)

**Any LLM call inside Python code — agents, LLM-as-judge, summarizers, extractors — goes
through Databricks Model Serving, not a provider SDK.** Do not `import anthropic` / `import openai`
to reach a model in code. Claude (and Llama, etc.) are served on Databricks Foundation Model APIs;
use that path.

Why: keeps cost/governance unified, serves as a reference architecture for other Databricks
users, and avoids splitting the auth surface across two SaaS providers.

### Golden path: `ChatDatabricks` (LangChain)

For LangChain/LangGraph code (the house default for Python agents), use `ChatDatabricks` from
`databricks_langchain`:

```python
from databricks_langchain import ChatDatabricks

# endpoint = a Foundation Model API name or your own serving endpoint name
llm = ChatDatabricks(endpoint="databricks-claude-sonnet-4")
llm.invoke("summarize this")
```

For non-LangChain code, use the OpenAI-compatible client pointed at the workspace, or
`mlflow.deployments.get_deploy_client("databricks")` — same endpoint, same auth model.

> **Concurrency / multi-profile note (from the runtime, #248 family):** bind a profile
> per-instance via `ChatDatabricks(endpoint=..., workspace_client=WorkspaceClient(profile=...))`
> rather than mutating the global `DATABRICKS_CONFIG_PROFILE` env var per call — the env var
> races under concurrent worker dispatch, the per-instance `workspace_client` does not. The
> runtime's model pool (`RPW_DATABRICKS_POOL`) does exactly this: one member per profile, each
> with independent FMAPI quota.

> **Library warts (confirmed live, not catchable by fake-member unit tests):**
> - `databricks_langchain` may forward a literal `tool_choice=None` that the underlying client
>   rejects — strip it before binding tools.
> - `ChatDatabricks(endpoint=..., max_retries=0)` raises because `max_retries` isn't always a
>   constructor kwarg. Do a **cheap live routing check** of any custom `BaseChatModel` wrapper
>   before trusting unit tests (the #232/#235/#236 lesson).

## Concern 2 — Endpoint create / config / query

### Golden path: define the endpoint, deploy, query — all profile-based

```bash
# Create/update a serving endpoint from a config file (idempotent: create then update-config).
# Auth is a named profile, every command. No PATs. (See "Auth" below.)
databricks serving-endpoints create --json @endpoint.json --profile DEFAULT
# ...or update an existing one's served entities:
databricks serving-endpoints update-config my-endpoint --json @served-entities.json --profile DEFAULT
```

```jsonc
// endpoint.json — a served model entity (scale-to-zero for cost; bump for latency-sensitive)
{
  "name": "my-endpoint",
  "config": {
    "served_entities": [
      {
        "entity_name": "main.models.my_model",   // UC-registered model
        "entity_version": "3",
        "workload_size": "Small",
        "scale_to_zero_enabled": true
      }
    ]
  }
}
```

Query it:

```bash
databricks serving-endpoints query my-endpoint \
  --profile DEFAULT \
  --json '{"inputs": [...]}'        # or {"messages": [...]} for chat endpoints
```

For programmatic queries from code, reuse the **Concern-1** path (`ChatDatabricks` /
OpenAI-compatible client) — same endpoint, no second auth mechanism.

### Auth passthrough for deployed agents

When you deploy an **agent** as a serving endpoint, the endpoint runs under a runtime identity —
there is no CLI and no `--profile` inside it. The agent must **declare the resources it needs at
deploy time** (the Genie space, the serving endpoints it calls, UC functions, vector indexes) so
Databricks provisions on-behalf-of-user / automatic auth passthrough for them. Resources not
declared at deploy time will fail auth at query time. This mirrors the deployed-runtime auth rule
in the **`dabs-environments`** skill: **code never branches on auth type — the environment decides
identity** (profile locally, SP env vars in CI, runtime identity + declared resources when deployed).

## Auth — profile only, no PATs (non-negotiable)

Same opinion as the rest of the suite: **no Personal Access Tokens anywhere.** No
`DATABRICKS_TOKEN`, no host/token pairs.

- **Local (humans):** OAuth U2M via `databricks auth login`, selected by a CLI profile. Always
  pass `--profile` (or set `DATABRICKS_CONFIG_PROFILE`).
- **CI/prod (machines):** service-principal OAuth M2M env vars, injected — never on disk.
- **Deployed endpoint:** runtime identity + declared resources (above).

## The ambiguous-host-profile crash class (#248) — the headline gotcha

This is the failure mode this skill exists to encode. When **two `~/.databrickscfg` profiles
share the same host** (e.g. a user profile and a service principal on one workspace — a perfectly
normal config), host-based default auth **cannot disambiguate** and crashes:

```
ValueError: default auth: databricks-cli: cannot get access token:
  Error: DEFAULT and ns-sp match https://<workspace>.cloud.databricks.com in ~/.databrickscfg.
  Use --profile to specify which profile to use
```

It surfaces at the **first model call** — e.g. a bare `ChatDatabricks(endpoint=...)` whose lazy
client constructs a `WorkspaceClient()` with host-based auth. The traceback is ~200 lines and
buries the one-line cause.

**Fix (validated live):**

```bash
export DATABRICKS_CONFIG_PROFILE=DEFAULT   # disambiguates the CLI/SDK default auth
# (in the runtime specifically, also: export RPW_DATABRICKS_POOL=DEFAULT)
```

Or, in code, bind the profile explicitly so default-auth disambiguation never runs:

```python
from databricks.sdk import WorkspaceClient
ChatDatabricks(endpoint="...", workspace_client=WorkspaceClient(profile="DEFAULT"))
```

| Symptom | Cause | Fix |
|---|---|---|
| `Use --profile to specify which profile to use` at first model call | 2+ profiles match one host | `export DATABRICKS_CONFIG_PROFILE=<profile>` or bind `WorkspaceClient(profile=...)` |
| `401 Credential was not sent or was of an unsupported type` | Same ambiguity, surfaced as 401 from the workspace | Same — pin the profile |
| Deployed agent 403s on a Genie space / endpoint it calls | Resource not declared at deploy time | Declare all called resources at deploy for auth passthrough |
| Custom `BaseChatModel` wrapper works in unit tests, fails live | `tool_choice=None` / `max_retries` forwarding wart | Cheap live routing check before trusting unit tests (#232/#235/#236) |

This is a sibling of the custom-ChatModel-wrapper live-failure family (#232/#235/#236): a class of
bug that fake-member unit tests cannot catch — which is why the rule is **do a cheap live routing
check first**.

## Related skills (the Databricks suite)

- **`databricks-jobs`** — sibling ops skill; jobs that call an LLM use the Concern-1 convention
  here, and share the profile-only auth opinion and the #248 crash class.
- **`dabs-environments`** (#240) — deploy endpoints/agents inside the standard DABs bundle;
  owns the dev/test/prod auth wiring and the "environment decides identity" principle.
- **`databricks-apps`** — for interactive/serving app frontends in front of an endpoint.
- **`databricks-uc-connections`** — when an endpoint/agent reaches an external service via a UC
  connection.
- **`python-with-uv`** — manage `databricks_langchain` / SDK deps with `uv`.
