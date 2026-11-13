# Snowflake → Unity Catalog translation

The pattern is Snowflake's access-role / functional-role hierarchy ("aligning object access with business functions"), with the conventional naming `<PROJECT>_<ENV>_{READ|WRITE|OWNER}` for access roles. Unity Catalog has no roles, only **account groups that nest**, so every edge has to be re-derived.

| Snowflake | Unity Catalog |
|---|---|
| `GRANT SELECT ... TO ROLE oar` | `` GRANT USE CATALOG, USE SCHEMA, SELECT ON CATALOG `c` TO `c_read` `` |
| `GRANT ROLE oar TO ROLE bfr` | add the **BFR group as a member of the OAR group** (arrow reversed) |
| `GRANT ROLE bfr TO USER u` | add the user to the BFR group |
| `ON ALL` + `ON FUTURE` boilerplate | not needed: privileges inherit catalog → schema → table |
| every role rolled up to `SYSADMIN` | `ALTER CATALOG c OWNER TO` an owner OAR whose member is the admin BFR |
| `USE ROLE` session scoping | none: every membership is always active (standing access) |

## Why the arrow reverses

In Snowflake a role *receives* another role and inherits its privileges, so the edge points from the access role to the functional role. In UC a grant lands on a group and flows **down** to everything inside it. To give a BFR the OAR's privileges, the BFR must be *inside* the OAR. Check any design by reading it aloud: "`sales_analyst` is a member of `sales_prod_read`". If the sentence says an OAR is a member of something, it is backwards.

## Rules that survive the translation

1. **Privileges land only on OARs; principals join only BFRs.** A direct grant to a user or to a BFR is a defect. Fold it into an OAR and revoke it.
2. **Scope OARs at catalog level, or schema level when one schema has a different audience. Never table.** Inheritance makes one catalog grant cover all current and future children. Table-level OARs are the role-explosion failure mode.
3. **Tiers.**
   - `read` = `USE CATALOG, USE SCHEMA, SELECT`.
   - `write` = `ALL PRIVILEGES`.
   - `owner` holds `OWNER TO` and no grants. The admin plane is a group, because people change teams.
   - A schema-scoped OAR also needs `USE CATALOG` on the parent catalog. The script emits it.
4. **Reuse before minting.** Create a new OAR only when a scope × tier is consumed differently by different BFRs.
5. **BFRs compose from OARs only.** Do not nest BFRs inside BFRs. Two jobs that share access share OAR memberships, not each other.
6. **Deliberate gaps are fine and should be commented in the role map.** A live federated catalog can carry an owner OAR and nothing else, so consumers read its snapshots instead. That absence is a decision, not an omission.

## Boundary notes

- **Account groups only.** Workspace-local groups (`users`, `admins`) cannot receive UC grants. Keep them for workspace ACLs.
- **Workspace object ACLs are a separate system.** Warehouses, jobs, clusters, apps and dashboards have their own permission model. This pattern does not cover them.
- **SCIM does not sync nested groups.** If an IdP owns the BFR groups, the BFR→OAR nesting edges must still be managed in Databricks, by this script or by automatic identity management.
- **No auto-membership.** An everyone-style group gets no native auto-join. Mark it `users: None` in the role map so the script leaves its members alone.
- **Standing access.** With no `USE ROLE`, a member of a write OAR always writes. Split BFRs when least privilege at session time matters.
- **dbt `+grants`.** Prefer the catalog-level read OAR. Inheritance already covers every model, so per-model grants are duplication. Use `+grants` only when a model needs a narrower audience than its catalog, and grant to an OAR.
