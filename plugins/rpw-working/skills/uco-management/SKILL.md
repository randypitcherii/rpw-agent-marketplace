---
name: uco-management
description: This skill should be used when the user mentions "UCO", "use case", or "use case object" in any context — including requests to find, list, count, filter, update, add, or ask questions about UCOs. Trigger on phrases like "show my UCOs", "how many UCOs", "what UCOs does this account have", "update a UCO", "create a UCO", "UCO status", "UCO health", "stale UCOs", "UCOs for [account/AE/SA]", or any question about use case lifecycle stages.
version: 1.0.0
---

# UCO Management Skill

Manage Salesforce Use Case Objects (UCOs) for Databricks Field Engineering. Covers querying, filtering, updating, and creating UCOs via the `sf` CLI.

## Prerequisites

- This skill expects a Salesforce auth helper skill (for example `salesforce-authentication`) to be available in the user's environment.
- Some reference workflows mention Databricks querying helpers (for example `databricks-query`) for bulk analysis.
- If these companion skills are unavailable, continue with the CLI commands in this skill and tell the user which optional helpers are missing.

## Authentication

Before any Salesforce operation, verify authentication using the `salesforce-authentication` skill:

```bash
sf org display 2>/dev/null | grep "Connected Status"
```

If not connected, run: `sf org login web --instance-url=https://<your-instance>.salesforce.com/`

Always pass `-o <username>` to all `sf` commands. Get the username from:
```bash
sf org display --json | jq -r '.result.username'
```

Store it and reuse: `SF_USER=$(sf org display --json | jq -r '.result.username')`

## Identity & Role Detection

Determine the current user's Salesforce identity and role to drive correct account filtering:

```bash
# Get user ID and role
sf data query -o "$SF_USER" --query "SELECT Id, Name, Title, UserRole.Name FROM User WHERE Username = '$SF_USER'" --json
```

**Role inference rules:**
- Title or UserRole contains "Solution Architect", "SA", or "RSA" → treat as **SA**
- Title or UserRole contains "Account Executive" or "AE" → treat as **AE**
- If indeterminate → default to **SA**

Store the user ID: `MY_ID=<Id from query>`

## Default Account Filtering

The default scope is always **all open UCOs (U2–U5) on the user's accounts**, regardless of who the UCO is assigned to. Account transitions happen frequently at Databricks — if you're on an account, those UCOs are your responsibility even if assigned to someone else.

**For SAs** — accounts where you are the primary SA:
```bash
Account__r.Last_SA_Engaged__c = '<MY_ID>'
```

**For AEs** — accounts you own:
```bash
Account__r.OwnerId = '<MY_ID>'
```

When presenting results, say "here are your active UCOs" — don't expose the technical filter details unless the user asks.

## SOQL Shell Gotchas

- **Use `<>` not `!=`** — zsh escapes `!=` as `\!=`, breaking queries
- **Always quote queries** in single quotes on the CLI
- **Always pass `-o <username>`** — no default org is set
- **Subqueries work** for account-based filtering: `Account__c IN (SELECT Id FROM Account WHERE ...)`

## Querying UCOs

### Default: All active UCOs on my accounts

```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name, Implementation_Status__c FROM UseCase__c WHERE Account__r.Last_SA_Engaged__c = '$MY_ID' AND Stages__c IN ('U2', 'U3', 'U4', 'U5') ORDER BY Account__r.Name, Stages__c"
```

### Filter by AE

```bash
# First get AE's user ID
sf data query -o "$SF_USER" --query "SELECT Id FROM User WHERE Name = 'Alex Example'" --json | jq -r '.result.records[0].Id'

# Then filter accounts by AE owner
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name, Implementation_Status__c FROM UseCase__c WHERE Account__r.Last_SA_Engaged__c = '$MY_ID' AND Account__r.OwnerId = '<AE_ID>' AND Stages__c IN ('U2', 'U3', 'U4', 'U5') ORDER BY Account__r.Name, Stages__c"
```

### Filter by account name

```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Implementation_Status__c, SAOwner__r.Name FROM UseCase__c WHERE Account__r.Name LIKE '%Acme Corp%' AND Stages__c IN ('U2', 'U3', 'U4', 'U5')"
```

### Search broadly (all UCOs, not just my accounts)

```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name FROM UseCase__c WHERE Name LIKE '%<SEARCH_TERM>%' AND Stages__c IN ('U2', 'U3', 'U4', 'U5')"
```

### Get a single UCO in full detail

```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name, Implementation_Status__c, Demand_Plan_Next_Steps__c, Full_Production_Date__c, Implementation_Start_Date__c, Implementation_Notes__c, UseCaseInPlan__c, DSA__r.Name FROM UseCase__c WHERE Id = '<UCO_ID>'"
```

## Updating UCOs

Always read the current state before updating next steps (to preserve existing content).

### Update health status (SA responsibility)
```bash
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <UCO_ID> \
  --values "Implementation_Status__c=Green"
# Valid: Green, Yellow, Red
```

### Update stage
```bash
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <UCO_ID> \
  --values "Stages__c=U3"
# Valid: U1, U2, U3, U4, U5, U6, Lost, Disqualified
```

### Prepend next steps entry
```bash
# 1. Read current next steps
CURRENT=$(sf data query -o "$SF_USER" --query "SELECT Demand_Plan_Next_Steps__c FROM UseCase__c WHERE Id = '<UCO_ID>'" --json | jq -r '.result.records[0].Demand_Plan_Next_Steps__c // ""')

# 2. Prepend new entry (newest first, format: Mon-DD - INITIALS - update text)
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <UCO_ID> \
  --values "Demand_Plan_Next_Steps__c='Feb-21 - XX - <UPDATE>\n$CURRENT'"
```

### Update target dates
```bash
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <UCO_ID> \
  --values "Implementation_Start_Date__c=2026-03-01 Full_Production_Date__c=2026-06-01"
```

### Combined weekly update
```bash
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <UCO_ID> \
  --values "Implementation_Status__c=Green Full_Production_Date__c=2026-06-01 Demand_Plan_Next_Steps__c='Feb-21 - XX - <UPDATE>\n<EXISTING>'"
```

## Creating a UCO

```bash
sf data create record -o "$SF_USER" --sobject UseCase__c \
  --values "Name='<UCO Name>' Account__c=<ACCOUNT_ID> Stages__c=U2 Implementation_Status__c=Green"
```

To find an account ID:
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name FROM Account WHERE Name LIKE '%<ACCOUNT_NAME>%'" --json
```

## Presenting Results

- Default listing: group by account, show stage + health status, count totals
- Lead with a clean summary table — don't expose filter logic
- Highlight Red/Yellow health, missing health status, or approaching live dates when relevant
- If no UCOs found: confirm the filter applied (my accounts, specific AE, etc.) and offer to search more broadly

## Additional Resources

- **`references/uco-fields.md`** — Full field reference, legacy vs active fields, stage definitions, next steps format
- **`references/soql-patterns.md`** — Common query patterns, bulk filtering, historical analysis via Logfood
