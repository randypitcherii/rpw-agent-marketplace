# UCO Field Reference

## Active vs Legacy Fields

| Purpose | Use This | Never Use |
|---------|----------|-----------|
| Status/health | `Implementation_Status__c` (Red/Yellow/Green) | `Status__c` (rarely populated) |
| Description | `Use_Case_Description__c` | `Description__c` (rarely populated) |
| Next steps | `Demand_Plan_Next_Steps__c` | `NextSteps__c` (legacy, not populated) |

## Core Fields

| Field | Type | Notes |
|-------|------|-------|
| `Name` | string(80) | UCO identifier |
| `Account__c` | reference | Parent account |
| `Opportunity__c` | reference | Associated opportunity |
| `Stages__c` | picklist | **Primary stage field** — U1–U6, Lost, Disqualified |
| `Implementation_Status__c` | picklist | Red / Yellow / Green — SA-owned health flag |
| `Active__c` | boolean | Whether UCO is active |
| `SAOwner__c` | reference | SA assigned to this UCO |
| `Primary_Solution_Architect__c` | reference | Primary SA |
| `Solution_Architect__c` | reference | SA (may differ from Primary SA) |
| `rsa__c` | reference | Regional SA |
| `DSA__c` | reference | Data Solutions Architect |
| `AEOwner__c` | reference | AE assigned to this UCO |

## Weekly Update Fields

| Field | API Name | Owner | Notes |
|-------|----------|-------|-------|
| Next Steps | `Demand_Plan_Next_Steps__c` | AE | Prepend newest entry at top |
| Target Onboarding Date | `Implementation_Start_Date__c` | AE | When $DBU usage starts |
| Target Live Date | `Full_Production_Date__c` | AE | When dev work completes |
| Use Case Health | `Implementation_Status__c` | SA | Green/Yellow/Red |
| Stage | `Stages__c` | AE/SA | U1–U6 lifecycle |
| Implementation Notes | `Implementation_Notes__c` | AE | Enablement, team, contact info |
| In Plan | `UseCaseInPlan__c` | AE | Boolean — treat like forecast category |
| DSA | `DSA__c` | DSA | Reference to DSA user |

## Stage Definitions

| Stage | Name | Definition | Clear Indicator |
|-------|------|------------|-----------------|
| U2 | Scoping | Pain identified, willingness to address | Customer willing to engage with SA |
| U3 | Evaluating | Customer agrees DB could be solution | Pilot/POC started |
| U4 | Confirming | Customer agrees DB is best solution | Tech Win from customer |
| U5 | Onboarding | Starting to use DBUs for this UCO | UCO driving $DBUs outside Pilot/POC |
| U6 | Live | Dev work completed, at MRR target | $DBU at steady state |

**Active SA tracking stages**: U2, U3, U4, U5 — always filter to these by default.

If a UCO has a product blocker, stage must remain U2 and AHAs must be linked.

## Next Steps Format

Entries prepended newest-first. Format: `Mon-DD - INITIALS - update text`

```
Feb-21 - RP - POC progressing, expect completion by end of month
Jan-05 - BK - Meeting with customer Monday to review architecture
Dec-11 - RZ - Block still finalizing design. Doc: https://docs.google.com/...
```

**Finding stale next steps**: `LastModifiedDate` tracks ANY field change, not specifically when next steps were updated. Parse the embedded date in `Demand_Plan_Next_Steps__c` text to determine actual staleness.

## Account Filtering Fields

| Role | Account Field | Description |
|------|--------------|-------------|
| SA | `Last_SA_Engaged__c` | SA currently engaged with the account |
| AE | `OwnerId` | AE who owns the account |

## Stage Tracking Metadata

- `CurrentStageDaysCount__c` — Days in current stage
- `Last_Stage_Modified_Date__c` — When stage last changed
- `Last_Stage_Modified_By__c` — Who last modified the stage
- `Stage_Numeric__c` — Numeric stage representation

## Implementation Notes Template

```
Enablement needed: Y/N
Enablement team engaged: Y/N
Implementation Contact: <name>
- Self Implementation: customer contact who owns project
- Partner Implementation: partner contact who owns project
- PS Implementation: PS adds note
```

## Health Status Meanings

| Status | Meaning |
|--------|---------|
| Green | On track to hit Target Live Date |
| Yellow | Some risk, but still achievable |
| Red | Significant risk or product blockers preventing progression |
