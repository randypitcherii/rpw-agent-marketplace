# Validation recipe

Run `apply_rbac.py --verify` after every apply. It automates the checks below. They are listed here so they can be run by hand when the script is not available.

## 1. Only OARs are grantees

```sql
SHOW GRANTS ON CATALOG <c>;      -- every principal must be an OAR group
SHOW GRANTS ON SCHEMA <c>.<s>;   -- for any schema-scoped OAR
SELECT catalog_name, catalog_owner
  FROM system.information_schema.catalogs;   -- owners should be *_owner groups
```

A person, a service principal or a BFR in that output is the smell. Fold it into an OAR and revoke the direct grant.

## 2. Access actually confers through the nesting

`SHOW GRANTS` proves where grants landed, but not that anyone receives them. That proof is per principal:

```bash
databricks api get "/api/2.1/unity-catalog/effective-permissions/catalog/<c>?principal=<email>"
```

A user with no direct grants who shows the OAR's privileges here, inherited from the OAR, is the pattern working end to end. An empty result for a user the role map says should read means the nesting is broken, and the usual cause is a reversed membership arrow. Use `.../effective-permissions/schema/<c>.<s>` for schema scopes.

## 3. Spot-check as the principal

When possible, have one member of each BFR run a `SELECT` against a table in each catalog their BFR should read, and an expected-to-fail `SELECT` against one it should not.
