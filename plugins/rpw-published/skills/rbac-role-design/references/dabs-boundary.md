# Hard boundary: never manage catalogs or grants as DABs resources

**Rule: catalogs and grants are managed by scripts and SQL, never by Databricks Asset Bundles.**

## What happened

The Databricks CLI supports `catalogs:` bundle resources with `grants:`, so governance-as-a-bundle looked natural. Four existing production catalogs were adopted with `databricks bundle deployment bind`, then deployed.

- The first deploy planned a **REPLACE** for all four catalogs. A replace is a drop, and the drop **cascaded** through every schema and table.
- The metastore used Default Storage, where Terraform **cannot create catalogs at all**. The recreate half of the replace failed, so the catalogs were simply gone.
- `UNDROP TABLE` refuses to restore into a recreated catalog of the same name, and `UNDROP CATALOG` does not exist.
- Real derived data was lost and had to be rebuilt from upstream.

Nothing in the bundle looked dangerous. The diff was "manage these catalogs", and the plan said destroy.

## If anyone retries anyway: both guards are mandatory

1. **Set the catalog resource's `lifecycle` destroy guard (`lifecycle: {prevent_destroy: true}`) before the first deploy.** Put it in the very first commit that declares the resource, not in a follow-up after a plan looks clean.
2. **Prove the plan on a throwaway catalog first.** Create a disposable catalog with a disposable table, then bind, deploy and re-deploy it. Only move on after the plan shows no replace and the table survives.

Read every `bundle deploy` plan for `replace` or `delete` on a catalog before approving it. Even with both guards, the role-map script is the house path: it can add access, but it cannot drop a catalog.
