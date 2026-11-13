# The declarative role-map script

`scripts/apply_rbac.py` is a template. Copy it into the project and edit only the `ROLE MAP` block. The file then holds the whole access model: the groups, the membership graph, and every grant those imply. Review the role map in a PR like any other code.

## Shape

- `SCOPES`: scope name → (`CATALOG` | `SCHEMA`, full name).
- `OARS`: scope → tiers. Each tier mints the group `<scope>_<tier>`.
- `BFRS`: job-named groups with `users`, `service_principals` and `member_of` (the OARs it is nested **into**). Set `users: None` to leave a group's membership unmanaged.

The validator runs first and refuses to plan if any of these are true:

- a BFR's `member_of` names another BFR, or an undeclared OAR;
- a BFR is named like an OAR (`*_read|_write|_owner`);
- a scope is table-level, or a scope name is malformed.

## Behaviour

| Flag | Effect |
|---|---|
| *(none)* | Dry run. Reads live state and prints the plan. Changes nothing. |
| `--offline` | Prints the full plan against an empty account. Needs no auth. Use it in review and for forward tests. |
| `--apply` | Creates groups, adds principals to BFRs, nests BFRs into OARs, and runs the grants. |
| `--apply --transfer-ownership` | Also runs `ALTER ... OWNER TO <scope>_owner`. Without the second flag, ownership lines print as skipped. |
| `--verify` | Read-only. Runs SHOW GRANTS and effective-permissions checks. Exits 1 on any defect. |

Plan order is fixed: create groups → principals into BFRs → BFRs into OARs → grants → ownership. Re-running is safe. Existing groups and memberships are skipped, and re-granting an existing privilege is a no-op. A principal missing from the account is reported as `MISSING` and skipped. Create it at the account level first; the script never invents identities.

Auth uses the `databricks` CLI. Pass `--account-profile` for groups and SCIM, and `--workspace-profile` plus `--warehouse-id` for SQL, or set `RBAC_ACCOUNT_PROFILE`, `RBAC_WORKSPACE_PROFILE` and `RBAC_WAREHOUSE_ID`.

## Why this shape

- **The human approves a printed plan, and the apply is exactly that plan.** That is also what lets it pass permission classifiers that block ad-hoc `GRANT`s.
- **Per-mutation-class gates.** Ownership transfer is the hardest change to undo, so it waits behind its own flag. Apply, verify, then transfer.
- **Revokes stay manual.** The script only adds. When `--verify` reports a non-OAR grantee, fold it into an OAR in the role map, re-apply, then `REVOKE` the direct grant by hand.

## Onboarding and offboarding

- Onboard: add the user to the right BFR's `users`, then dry run and apply.
- Offboard: remove the user from the role map, and also remove the membership in the account. The script does not remove members, so the account console or SCIM is the delete path.
- A new service principal joins one BFR, and nothing else changes.
