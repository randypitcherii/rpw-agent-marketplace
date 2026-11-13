---
name: rbac-role-design
description: Unity Catalog access control as a strict two-tier split — object access roles (OARs) hold every grant, business function roles (BFRs) hold every human and service principal. Load BEFORE any GRANT/REVOKE or ownership change, new catalog or schema permissions, adding a user or service principal, onboarding/offboarding, "who can read X", or any "give X access to Y". Ships an idempotent dry-run-first role-map script. Never manage catalogs/grants as DABs resources.
---

# RBAC role design — object access roles vs business function roles

## Read this first: the membership arrow REVERSES

Unity Catalog has no roles, only account groups that nest, and a grant to a group flows **down** to its transitive members. So Snowflake's `GRANT ROLE oar TO ROLE bfr` becomes **add the BFR group as a MEMBER of the OAR group**. The OAR is the parent; the BFR is the child. Flip it (OARs as members of BFRs) and the hierarchy looks right in the UI and grants nothing.

## The pattern (two tiers, no exceptions)

- **OARs** are the ONLY grantees of object privileges. One per securable scope × tier, named `<scope>_{read|write|owner}`. Scope at catalog (or schema) level, **never table**. An OAR never holds a person or service principal directly.
- **BFRs** are the ONLY groups people and service principals join. Named for jobs (`sales_analyst`, `sales_pipeline`). Zero direct grants: they compose access purely by being nested inside OARs. A service principal gets a BFR exactly like a human.

Every access change becomes one membership edit. "Give X access to Y" means: put X in the right BFR, or nest that BFR in Y's OAR. It is never a new `GRANT` to a person. Tiers: `read` = `USE CATALOG, USE SCHEMA, SELECT`; `write` = `ALL PRIVILEGES`; `owner` receives `OWNER TO`. Translation table and tier rules: [references/translation.md](references/translation.md).

## The mechanism: one declarative role-map script

Copy [scripts/apply_rbac.py](scripts/apply_rbac.py) into the project, replace its `ROLE MAP` block, and make every access change there. Never hand-issue a grant that bypasses it.

```bash
uv run --no-project python apply_rbac.py --offline   # full plan, no auth
uv run --no-project python apply_rbac.py             # dry run vs live state (default)
uv run --no-project python apply_rbac.py --apply     # groups, memberships, grants
uv run --no-project python apply_rbac.py --apply --transfer-ownership
uv run --no-project python apply_rbac.py --verify    # read-only proof
```

Show the human the printed plan, then apply exactly that plan. Gates, idempotency and the validator: [references/role-map-script.md](references/role-map-script.md).

## Validate, don't assume

1. `SHOW GRANTS ON CATALOG <c>` must list **only OAR grantees**. A user or BFR there is a defect: fold it into an OAR and revoke it.
2. Per principal, `GET /api/2.1/unity-catalog/effective-permissions/catalog/<c>?principal=<email>` must show the OAR's privileges. That is the proof that access confers through the nesting.

Recipe: [references/validation.md](references/validation.md).

## Hard boundary: catalogs and grants are scripts + SQL, never DABs

Bind-adopting four existing catalogs into a bundle and deploying planned a REPLACE that **dropped all four**, and the data was not recoverable. If anyone retries anyway, both guards are mandatory: set the catalog resource's `lifecycle` destroy guard **before the first deploy**, and **prove the plan on a throwaway catalog**. Full incident: [references/dabs-boundary.md](references/dabs-boundary.md).

## Boundary notes

- Only **account** groups can receive UC grants. Workspace-local groups cannot.
- Workspace ACLs (warehouses, jobs) are a separate system, outside this pattern.
- SCIM does not sync nested groups. Manage the BFR→OAR edges in Databricks.
- UC privileges inherit catalog → schema → table, so `ON ALL` / `ON FUTURE` is unnecessary.
- Nesting is standing access. There is no `USE ROLE`.
