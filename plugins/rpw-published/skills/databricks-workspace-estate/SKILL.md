---
name: databricks-workspace-estate
description: Discover and qualify Databricks accounts and workspaces available to a user email, then build a human-approved workspace pool. Use when asked to find Databricks accounts, enumerate workspace access, scan an account estate, expand an LLM workspace pool, or turn the login.databricks.com account chooser into Databricks CLI account profiles.
portability: portable
---

# Discover a Databricks workspace estate

Use the email-based account chooser to find account boundaries, the Accounts API to enumerate
workspaces, and workspace APIs to prove actual access. Authentication is reach, not consent:
never send prompts, code, or tool output to a workspace until a human approves that workspace
and its account.

## Capabilities

- Discover every Databricks account shown for one authenticated user email.
- Create one OAuth account profile per account and list its workspaces without creating hundreds
  of workspace profiles.
- Separate “listed by the account” from “workspace token accepted” and “model serving works.”
- Build an explicit `proposed` → `approved` or `denied` review queue for pooled workloads.

## Workflow

### 1. Discover accounts from the user email

The Databricks CLI has no global “accounts for email” command. The authenticated web login is
the discovery surface:

1. Open `https://login.databricks.com/`.
2. Authenticate with the requested email or its configured identity provider.
3. Continue to `https://login.databricks.com/select-account`.
4. Record every account card’s display name and cloud badge.
5. Inspect the card link or select the account. Account buttons hard-navigate through
   `/login/accounts`; the resulting account-console URL and request identify the account ID and
   account host.

Use a browser snapshot for card names and DevTools network/DOM inspection for link targets. Do
not infer an account ID from its display name.

### 2. Create and verify account profiles

Create one named OAuth profile per account:

```bash
databricks auth login \
  --host "https://accounts.cloud.databricks.com" \
  --account-id "<account-id>" \
  --profile "<descriptive-account-profile>"
```

Use the cloud-specific account host shown by the login flow. Then verify:

```bash
databricks auth profiles -o json
databricks account workspaces list \
  --profile "<descriptive-account-profile>" \
  -o json
```

The account listing proves account visibility only. It does not prove that the account bearer
is accepted by each workspace.

### 3. Probe workspace access without adding profiles

Derive each workspace host from the account host and its `deployment_name`. For example,
`https://accounts.cloud.databricks.com` plus `my-workspace` becomes
`https://my-workspace.cloud.databricks.com`.

Use the account profile’s fresh OAuth headers to probe:

```text
GET <workspace-host>/api/2.0/preview/scim/v2/Me
```

Interpret results strictly:

| Result | Meaning |
|---|---|
| `200` | The account token reaches this workspace. Continue qualification. |
| `401` | The account can list the workspace, but its bearer is not accepted there. Do not pool it. |
| `403` with missing workspace entitlement | The user lacks workspace access. Do not pool it. |
| `429` | Unknown; retry with bounded concurrency and backoff. Never treat it as approval. |

Cap concurrent probes. Large accounts can contain hundreds of workspaces; scanning all of them
at once creates rate limits and slow service startup.

### 4. Qualify model serving

For reachable workspaces, read the inventory:

```text
GET <workspace-host>/api/2.0/serving-endpoints
```

Keep only READY foundation-model endpoints whose `api_types` declare a chat protocol. Before
recommending a workspace, run small bounded checks against both routes:

```text
POST <workspace-host>/serving-endpoints/anthropic/v1/messages
POST <workspace-host>/serving-endpoints/v1/chat/completions
```

Use a cheap model, a non-sensitive prompt such as `Reply exactly: ok`, and a small token limit.
Deduplicate candidates by workspace ID so an account-sourced member does not duplicate an
existing workspace profile.

### 5. Require human approval

Present candidates with account, workspace display name, workspace ID, model counts, and live
route results. Name every workspace in the approval question.

Maintain three durable states:

- `proposed`: discovered and tested, but receives no pooled traffic.
- `approved`: the human consented to prompts, code, and tool output being sent there.
- `denied`: never pool it and do not repeatedly propose it.

Approval requires both the account and workspace gates. A successful login, `200` probe, rich
model catalog, or prior use never substitutes for consent.

### 6. Integrate with rpw-llm-proxy when available

The rpw proxy already implements the two-gate registry and account-token members:

```bash
python -m rpw_llm_proxy.pool_estate
python -m rpw_llm_proxy.pool_estate --approve-account "<account-id>"
python -m rpw_llm_proxy.pool_estate --approve "<account-profile>/<deployment-name>"
python -m rpw_llm_proxy.pool_estate --deny "<member-name>"
```

`RPW_DATABRICKS_ACCOUNTS` narrows account profiles; it cannot add access. Review with
`--no-discover` when no network or registry mutation is wanted.

Do not approve a large account before checking startup cost. Account discovery lists and probes
the account estate at service start. An account with hundreds of workspaces needs a narrower
discovery mechanism or selected workspace profiles before it is suitable for a resident proxy.

After approval, restart once, verify health reports the expected members with no evictions, and
drive enough cheap requests to observe each new member return `200`.

## Examples

### “Find every Databricks workspace I can access”

Open the email account chooser, create account profiles, list workspaces per account, probe
workspace entitlement, and return a qualified proposal table. Do not approve anything.

### “Expand my Databricks LLM pool”

Run discovery and model qualification, remove duplicate workspace IDs, ask for named account and
workspace approvals, apply only those decisions, then verify rotation.

### “Why does an account list 498 workspaces but none can serve?”

Test a workspace API with the account bearer. A `401` means account enumeration works while
workspace token passthrough does not; do not create or approve hundreds of unusable members.
