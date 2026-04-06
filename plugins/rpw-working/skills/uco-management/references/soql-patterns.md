# SOQL Patterns for UCO Management

## Shell Gotchas

- **`<>` not `!=`** — zsh shell escapes `!=` as `\!=`, causing SOQL parse errors
- **`-o <username>`** — always pass the org flag; no default is set
- **Single-quote queries** on the CLI to prevent shell interpolation issues
- **Cross-object filters work**: `Account__r.Last_SA_Engaged__c = 'USER_ID'` traverses the relationship correctly

## Core Query Patterns

### All active UCOs on my accounts (SA)
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name, Implementation_Status__c FROM UseCase__c WHERE Account__r.Last_SA_Engaged__c = '$MY_ID' AND Stages__c IN ('U2', 'U3', 'U4', 'U5') ORDER BY Account__r.Name, Stages__c"
```

### All active UCOs on my accounts (AE)
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name, Implementation_Status__c FROM UseCase__c WHERE Account__r.OwnerId = '$MY_ID' AND Stages__c IN ('U2', 'U3', 'U4', 'U5') ORDER BY Account__r.Name, Stages__c"
```

### Filter by AE on SA's accounts
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name FROM UseCase__c WHERE Account__r.Last_SA_Engaged__c = '$MY_ID' AND Account__r.OwnerId = '<AE_ID>' AND Stages__c IN ('U2', 'U3', 'U4', 'U5') ORDER BY Account__r.Name, Stages__c"
```

### UCOs where I'm explicitly the SAOwner
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name FROM UseCase__c WHERE SAOwner__c = '$MY_ID' AND Stages__c IN ('U2', 'U3', 'U4', 'U5')"
```

### UCOs on my accounts where I'm NOT the SAOwner
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name FROM UseCase__c WHERE Account__r.Last_SA_Engaged__c = '$MY_ID' AND SAOwner__c <> '$MY_ID' AND Stages__c IN ('U2', 'U3', 'U4', 'U5')"
```

### UCOs for a specific account (by name)
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Implementation_Status__c, SAOwner__r.Name FROM UseCase__c WHERE Account__r.Name LIKE '%Acme Corp%' AND Stages__c IN ('U2', 'U3', 'U4', 'U5')"
```

### Full UCO detail (for updates/reviews)
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Stages__c, Account__r.Name, SAOwner__r.Name, Implementation_Status__c, Demand_Plan_Next_Steps__c, Full_Production_Date__c, Implementation_Start_Date__c, Implementation_Notes__c, UseCaseInPlan__c, DSA__r.Name FROM UseCase__c WHERE Id = '<UCO_ID>'"
```

### Count UCOs by stage for my accounts
```bash
sf data query -o "$SF_USER" --query "SELECT Stages__c, COUNT(Id) total FROM UseCase__c WHERE Account__r.Last_SA_Engaged__c = '$MY_ID' AND Stages__c IN ('U2', 'U3', 'U4', 'U5') GROUP BY Stages__c ORDER BY Stages__c"
```

## Lookup Helpers

### Find a user by name
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, Email, Title, UserRole.Name FROM User WHERE Name LIKE '%Alex Example%' AND IsActive = true"
```

### Get current user identity + role
```bash
SF_USER=$(sf org display --json | jq -r '.result.username')
sf data query -o "$SF_USER" --query "SELECT Id, Name, Title, UserRole.Name FROM User WHERE Username = '$SF_USER'" --json
```

### Find an account by name
```bash
sf data query -o "$SF_USER" --query "SELECT Id, Name, OwnerId, Owner.Name, Last_SA_Engaged__c FROM Account WHERE Name LIKE '%<NAME>%'"
```

## Logfood SQL (for read-heavy or historical queries)

For bulk reads, Logfood SQL (Databricks SQL against `<catalog>.sfdc_bronze`) is 2–10x faster than SOQL. Substitute your environment's catalog name for `<catalog>`. Use the `databricks-query` skill or Databricks CLI with `--profile=logfood`.

**Critical**: Always filter by `processDate` — tables contain full daily snapshots.

### All active UCOs for an SA's accounts
```sql
SELECT uc.Id, uc.Name, uc.Stages__c, uc.Implementation_Status__c,
       a.Name as account_name, su.Name as sa_owner
FROM <catalog>.sfdc_bronze.usecase__c uc
JOIN <catalog>.sfdc_bronze.account a ON uc.Account__c = a.Id
LEFT JOIN <catalog>.sfdc_bronze.user su ON uc.SAOwner__c = su.Id
WHERE uc.processDate = (SELECT MAX(processDate) FROM <catalog>.sfdc_bronze.usecase__c)
AND a.processDate = (SELECT MAX(processDate) FROM <catalog>.sfdc_bronze.account)
AND a.Last_SA_Engaged__c = '<MY_ID>'
AND uc.Stages__c IN ('U2', 'U3', 'U4', 'U5')
ORDER BY a.Name, uc.Stages__c
```

### Historical: Track a UCO's stage changes
```sql
SELECT processDate, Stages__c, Implementation_Status__c, Full_Production_Date__c
FROM <catalog>.sfdc_bronze.usecase__c
WHERE Id = '<UCO_ID>'
ORDER BY processDate DESC
LIMIT 30
```

### Find UCOs where go-live date was pushed out
```sql
WITH current AS (
    SELECT Id, Name, Full_Production_Date__c as current_date
    FROM <catalog>.sfdc_bronze.usecase__c
    WHERE processDate = (SELECT MAX(processDate) FROM <catalog>.sfdc_bronze.usecase__c)
    AND Stages__c IN ('U2', 'U3', 'U4', 'U5')
),
two_weeks_ago AS (
    SELECT Id, Full_Production_Date__c as old_date
    FROM <catalog>.sfdc_bronze.usecase__c
    WHERE processDate = DATE_SUB((SELECT MAX(processDate) FROM <catalog>.sfdc_bronze.usecase__c), INTERVAL 14 DAY)
)
SELECT c.Name, c.current_date, t.old_date,
       DATEDIFF(c.current_date, t.old_date) as days_pushed
FROM current c
JOIN two_weeks_ago t ON c.Id = t.Id
WHERE c.current_date > t.old_date
ORDER BY days_pushed DESC
```

## Data Source Decision

| Task | Use | Why |
|------|-----|-----|
| Query/list/count | SOQL via sf CLI | Simple, no extra auth needed |
| Bulk reads, joins, analysis | Logfood SQL | 2–10x faster, supports SQL joins |
| Historical/lifecycle tracking | Logfood SQL | Daily snapshots — SOQL only returns current state |
| Any write (update/create) | SOQL via sf CLI | Logfood is read-only |
