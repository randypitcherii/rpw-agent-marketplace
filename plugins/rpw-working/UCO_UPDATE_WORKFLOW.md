# UCO Update Workflow

A structured, AI-assisted workflow for reviewing and updating Salesforce Use Case Objects (UCOs). Dispatches parallel research agents across Gmail, Google Calendar, Google Drive, Slack, and Glean, then walks through each proposed change interactively for human approval before applying to Salesforce.

---

## Prerequisites

- **Salesforce CLI** (`sf`) authenticated to your Salesforce instance
- **MCP tools available**: Google (Gmail, Calendar, Drive), Slack, Glean
- **User's Salesforce User ID and role** (SA vs AE) -- determined automatically in Step 1

---

## Step 1: Discover UCOs

### 1a. Authenticate and Identify User

```bash
SF_USER=$(sf org display --json | jq -r '.result.username')
sf data query -o "$SF_USER" --query "SELECT Id, Name, Title, UserRole.Name FROM User WHERE Username = '$SF_USER'" --json
```

Store the user's Salesforce ID for subsequent queries:
```bash
MY_ID=<Id from query>
```

### 1b. Query Active UCOs

Query active UCOs (stages U2 through U5), filtered by role:

**For SAs** (filter by Last SA Engaged):
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Account__r.Name, Stages__c, \
  Implementation_Status__c, Demand_Plan_Next_Steps__c, \
  Implementation_Start_Date__c, Full_Production_Date__c, LastModifiedDate \
  FROM UseCase__c \
  WHERE Account__r.Last_SA_Engaged__c = '$MY_ID' \
  AND Stages__c IN ('U2','U3','U4','U5') \
  ORDER BY Account__r.Name, Stages__c" --json
```

**For AEs** (filter by Account Owner):
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Account__r.Name, Stages__c, \
  Implementation_Status__c, Demand_Plan_Next_Steps__c, \
  Implementation_Start_Date__c, Full_Production_Date__c, LastModifiedDate \
  FROM UseCase__c \
  WHERE Account__r.OwnerId = '$MY_ID' \
  AND Stages__c IN ('U2','U3','U4','U5') \
  ORDER BY Account__r.Name, Stages__c" --json
```

**Optional AE filter**: To scope to a specific AE's accounts, first find the AE's user ID:
```bash
AE_ID=$(sf data query -o "$SF_USER" --query "SELECT Id FROM User WHERE Name = '<AE Name>'" --json | jq -r '.result.records[0].Id')
```
Then add `AND Account__r.OwnerId = '$AE_ID'` to the UCO query.

### 1c. Present Summary

Group UCOs by account and display:
- UCO name, stage, and health status (Green/Yellow/Red or **missing**)
- Last modified date
- **Staleness flag**: warn if no update in 60+ days
- **Missing health flag**: SA should always maintain health — flag any UCOs without a status
- **Priority grouping**: Red/Yellow health first, then by stage

---

## Step 2: Research Phase (Parallel Agents)

For each account, dispatch **two parallel research agents** (use `general-purpose` subagent type). Both search across all available data sources.

### Research Agent A: New UCO Discovery

**Goal**: Identify use cases being worked that don't have a corresponding UCO yet.

**Process**:
1. Search all data sources for account activity in the last 2 weeks
2. Cross-reference findings against existing UCOs to identify gaps
3. For each potential new UCO, propose:
   - **Name**: Descriptive, **business-outcome-focused** (not tech-stack-focused)
   - **Stage**: Recommended starting stage (typically U2 or U3)
   - **Rationale**: Why this UCO should exist, with evidence
   - **Key Contacts**: Customer stakeholders involved
   - **Estimated Spend**: If discoverable from context

### Research Agent B: Existing UCO Updates

**Goal**: Determine what changes (if any) should be made to each existing UCO.

**Process**:
1. For each existing UCO, dispatch a **parallel sub-agent** (use `Explore` subagent type to preserve parent context)
2. Each sub-agent searches all data sources for UCO-specific activity
3. For each UCO, propose changes to any of:
   - **Health** (Green / Yellow / Red) -- SA-owned field
   - **Stage** (U2-U6) -- AE-owned field
   - **Next Steps** -- prepend new entry in format: `Mon-DD - INITIALS - Update text`
   - **Target Dates** (Implementation Start, Full Production) -- AE-owned field
   - **Name change** -- if current name is tech-focused, suggest business-outcome rename
   - **Split recommendation** -- if UCO covers multiple distinct workstreams
4. Include rationale and evidence citations for every proposed change

### Data Source Search Strategy

**Use Glean as the PRIMARY search tool.** Glean indexes across Gmail, Calendar, Drive, Slack, Jira, Confluence, and more. It surfaces cross-source context that individual searches miss — competitive losses, champion departure risks, internal escalations, pricing discussions, etc.

In testing, Glean changed 3 out of 8 health recommendations vs. individual tool searches alone by surfacing competitive losses, well-defined use cases with active work, and partnership blockers that individual searches missed entirely.

**Supplement with individual MCP tool searches** for targeted queries that Glean may not fully cover (e.g., specific email threads, calendar event details, Slack thread context).

See [Example Searches](#example-searches) below for query patterns.

---

## Step 3: Review Phase (Interactive)

### 3a. Create Working Folder Structure

```
uco_updates/
  {YYYY-MM-DD}/
    new_ucos/
      {account}-{uco-name}.md
    uco_changes/
      {NN}-{account}-{uco-name}.md    # numbered for ordering
```

Each markdown file contains:
- Current state (for existing UCOs)
- Proposed changes with before/after values
- Rationale and evidence
- Approval status (updated during review)

### 3b. Initialize Work Tracking (Optional)

Use beads to track all proposed changes as issues:
```bash
bd init uco-updates
# Create one issue per new UCO proposal and one per existing UCO change
```

### 3c. Walk Through Changes One-by-One

**Order**: New UCOs first (require the most judgment), then existing UCO changes grouped by account.

For each proposed change, present:
1. What the change is (current vs. proposed)
2. Evidence/rationale from research
3. Wait for user response: **approve**, **modify**, or **reject**

**Common user modifications during review** (expect these):

| Pattern | Example |
|---------|---------|
| **Stage advancement** | "Let's advance the stage too — she's implementing now" |
| **UCO splitting** | "Split this into two — keep PII analytics, create new one for AI testing" |
| **UCO renaming** | "Update the title to focus on the business use case, not the tech" |
| **Scope expansion** | "This now uses LangGraph + MLflow + Databricks Apps, not just Genie" |
| **Date adjustment** | "Target live to April" |
| **Blocker attachment** | "Attach a blocker for missing Genie API scoped credentials" |
| **Advance to done** | "Actually advance this all the way to U6 — it's implemented" |
| **Spawn new UCO** | "Create a new UCO for the Slackbot delivery model at U2" |

These modifications are the core value of the interactive review — the AI proposes, the human reshapes with context the AI doesn't have.

### 3d. UCO Naming Best Practice

Names should be **business-outcome-focused**, not tech-stack-focused. But DO mention key Databricks products when relevant.

| Bad | Good |
|-----|------|
| Analytics Team - Genie | Agentic Analytics Experience for [Customer] Clients (Lakebase + Apps) |
| DevEng GenAI Agent | AI Testing & Validation Agent (Eng + Analytics) |
| Slackbot Project | Databricks Apps Slackbot - Agent Delivery Platform |

Avoid abbreviations that collide with common business titles (e.g., "COO" reads as "Chief Operating Officer" — spell it out instead).

---

## Step 4: Apply Changes

### Salesforce API Field Reference

| What to Update | API Field | Example Value |
|----------------|-----------|---------------|
| Next Steps | `Demand_Plan_Next_Steps__c` | `Feb-23 - XX - Update text` |
| Target Onboarding | `Implementation_Start_Date__c` | `2026-03-01` |
| Target Live | `Full_Production_Date__c` | `2026-06-01` |
| Health | `Implementation_Status__c` | `Green`, `Yellow`, `Red` |
| Stage | `Stages__c` | `U2`, `U3`, `U4`, `U5`, `U6` |
| UCO Name | `Name` | Business-outcome-focused title |

**IMPORTANT**: The Next Steps field is `Demand_Plan_Next_Steps__c` (NOT `Next_Steps__c`).

### Simple Field Updates (sf CLI)

For short values (health, stage, dates), `sf --values` works fine:

```bash
# Update health
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <ID> \
  --values "Implementation_Status__c=Green"

# Update stage
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <ID> \
  --values "Stages__c=U3"

# Update dates
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <ID> \
  --values "Implementation_Start_Date__c=2026-03-01 Full_Production_Date__c=2026-06-01"

# Combined simple update
sf data update record -o "$SF_USER" --sobject UseCase__c --record-id <ID> \
  --values "Implementation_Status__c=Green Stages__c=U3 Full_Production_Date__c=2026-06-01"
```

### Long Text Updates (REST API via curl)

**CRITICAL**: The `sf --values` flag breaks on long text containing dashes, apostrophes, or special characters. It parses spaces as key=value delimiters, so text like `"Customer delayed Decision - Alex Example"` gets misinterpreted.

**Use Salesforce REST API via curl instead** for Next Steps and any long text:

```bash
# 1. Get access token and instance URL
ACCESS_TOKEN=$(sf org display -o "$SF_USER" --json | jq -r '.result.accessToken')
INSTANCE_URL=$(sf org display -o "$SF_USER" --json | jq -r '.result.instanceUrl')

# 2. Read current Next Steps
CURRENT=$(sf data query -o "$SF_USER" --query \
  "SELECT Demand_Plan_Next_Steps__c FROM UseCase__c WHERE Id = '<ID>'" --json \
  | jq -r '.result.records[0].Demand_Plan_Next_Steps__c // ""')

# 3. Write JSON body with new entry prepended
cat > /tmp/uco_update.json << 'JSONEOF'
{
  "Demand_Plan_Next_Steps__c": "Feb-23 - XX - New update text here.\n<EXISTING CONTENT HERE>"
}
JSONEOF

# 4. PATCH via REST API
curl -s -X PATCH "$INSTANCE_URL/services/data/v59.0/sobjects/UseCase__c/<ID>" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d @/tmp/uco_update.json

# 5. Clean up
rm /tmp/uco_update.json
```

**Why this works**: JSON body avoids all shell escaping issues. The REST API accepts the full text faithfully.

### Create New UCO

```bash
sf data create record -o "$SF_USER" --sobject UseCase__c \
  --values "Name='<UCO Name>' Account__c=<ACCOUNT_ID> Stages__c=U2 Implementation_Status__c=Green"
```

Then use REST API to set Next Steps (long text).

### Verify After Every Update

```bash
sf data query -o "$SF_USER" --query "SELECT Name, Stages__c, Implementation_Status__c, \
  Implementation_Start_Date__c, Full_Production_Date__c \
  FROM UseCase__c WHERE Id = '<ID>'" --json
```

### Known Salesforce Validation Rules

| Rule | Trigger | Workaround |
|------|---------|------------|
| **U6 requires Customer Tech Lead** | Moving `Stages__c` to `U6` | Must add a `UseCaseTeamMember__c` junction record with Role = "Customer Tech Lead" via SFDC UI first. The `User__c` field references internal Salesforce Users, not Contacts — external contacts must be added through the UI. Set to U5 and note the manual step. |

---

## Step 5: Communicate Changes

Generate Slack messages summarizing all changes, **grouped by account** (one message per account). Send to the AE.

### Message Format

```
:robot_face: *Robot-generated UCO update — please review*

:office: *{Account Name} UCO Updates — {Date}*

:new: *New UCOs Created*
- *{UCO Name}* — {Stage} | {brief description}

:arrows_counterclockwise: *Updated UCOs*
- *{UCO Name}* — {what changed} | {key context}
- *{UCO Name}* — {what changed} | {key context}

:pushpin: *Action Items*
- {anything needing AE attention}
```

### Sending via Slack MCP

1. Find the AE's Slack user ID via `slack_read_api_call` with `users.lookupByEmail`
2. Open a DM channel with `slack_write_api_call` using `conversations.open`
3. Send the message with `slack_write_api_call` using `chat.postMessage`

Use tasteful emojis for scannability. Include "robot-generated" header so the AE knows it's AI-assisted.

---

## Example Searches

### Glean (Primary - Cross-Source)

Use `glean_read_api_call` with the search endpoint.

| Query Pattern | Purpose |
|---|---|
| `"{Account Name} Databricks"` | General account activity |
| `"{Contact Name}"` | Person-specific activity |
| `"{UCO topic} {Account Name}"` | UCO-specific research |
| `"Lakebase pricing"` or `"compute pricing"` | Pricing/sizing context |
| `"{Account Name} competitive"` or `"{Account Name} Snowflake"` | Competitive intelligence |
| `"{Contact Name} departure"` or `"{Contact Name} leaving"` | Champion risk detection |

### Gmail (via Google MCP)

Use `google_read_api_call` with the Gmail API.

- **Endpoint**: `gmail/v1/users/me/messages`
- **Parameters**: `q` for search query, `maxResults` for count
- **Example**: `q="Acme Corp after:2026/02/08 before:2026/02/23"`
- **Then fetch full message**: `gmail/v1/users/me/messages/{messageId}`

### Google Calendar (via Google MCP)

Use `google_read_api_call` with the Calendar API.

- **Endpoint**: `calendar/v3/calendars/primary/events`
- **Parameters**: `timeMin`, `timeMax` (RFC3339), `q` for search
- **Example**: `timeMin=2026-02-08T00:00:00Z&timeMax=2026-02-23T00:00:00Z&q=Acme Corp`

### Google Drive (via Google MCP)

Use `google_read_api_call` with the Drive API.

- **Endpoint**: `drive/v3/files`
- **Parameters**: `q` for search query
- **Example**: `q="name contains 'Acme Corp' and modifiedTime > '2026-02-08T00:00:00'"`

### Slack (via Slack MCP)

Use `slack_read_api_call` to search messages.

- **Endpoint**: `search.messages`
- **Parameters**: `query` for search text
- **Search by**: account name, contact names, UCO topics

### Salesforce (via sf CLI)

- Always wrap SOQL in **single quotes**
- Use `<>` instead of `!=` (zsh escaping issue with `!`)
- Always pass `-o <username>` to every `sf` command
- Use `--json` when you need to parse output programmatically

---

## Key Learnings & Gotchas

### Salesforce CLI

- **Always pass `-o <username>`** to every `sf` command — no default org is set
- **Use `<>` not `!=`** in SOQL — zsh escapes `!=` as `\!=`, breaking queries
- **`sf --values` breaks on long text** — dashes, apostrophes, and spaces in values get misinterpreted as key=value delimiters. Use REST API via curl for `Demand_Plan_Next_Steps__c` and other long text fields.
- **The Next Steps field is `Demand_Plan_Next_Steps__c`** — NOT `Next_Steps__c`
- **Stage values** use format `U2`, `U3`, etc. (NOT `2-Scoping`, `3-Evaluating`)
- **U6 blocked by validation rule** requiring Customer Tech Lead — set via `UseCaseTeamMember__c` junction object in SFDC UI, not via CLI

### Research

- **Glean first, always.** It changed 3 of 8 health recommendations in testing. Individual tool searches miss cross-source context.
- **Champion risk detection** is a key Glean strength — it surfaces departure signals from email/Slack/calendar that individual searches miss.
- **Competitive context** from Glean helps calibrate health status more accurately than activity-only signals.

### Interactive Review

- **Users will reshape proposals significantly.** The AI proposes a starting point; expect 50%+ of proposals to be modified. This is the design, not a failure.
- **UCO splitting is common.** When a UCO covers two distinct workstreams, users often ask to split into separate UCOs mid-review.
- **Business-outcome naming.** Users consistently prefer names that describe what the customer gets, not what tech is used. But mentioning key Databricks products (Lakebase, Apps, etc.) in the name is fine.
- **Stage advancement** is frequently added by users — research agents tend to be conservative on stage, users add context the research didn't find.
- **Avoid abbreviations** that collide with business titles or common terms (COO, CTO, etc.).

### Architecture

- **Parallel agents per account** (new UCO discovery + existing UCO updates) minimize wall-clock time
- **Explore sub-agents per UCO** within the existing-updates agent preserve parent context
- **Beads issue tracking** provides persistent tracking across sessions for multi-day UCO management
- **Folder structure** (`uco_updates/{date}/new_ucos/` + `uco_changes/`) creates an audit trail

### Slack Communication

- **One message per account** — don't combine accounts in a single message
- **"Robot-generated" header** — sets expectations that this is AI-assisted, not manually written
- **Tasteful emojis** — improves scannability in Slack but don't overdo it
- **Action items section** — call out anything needing AE follow-up separately
