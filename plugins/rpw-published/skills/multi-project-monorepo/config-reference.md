# Publish config reference

Companion to `SKILL.md`. Concrete shapes for the per-target publish config. Repo and
package names below are placeholders — substitute your own.

## Single-target config

Start here. One file at the repo root, one public target.

```yaml
# publish-config.yml — include model (FAIL-SAFE).
# The mirror contains ONLY the paths named below. New repo content is
# UNPUBLISHED by default; you must add it here to ship it.
# The include list IS the privacy boundary. The exclude globs are not.

include:
  # Copied VERBATIM — same path in the target repo.
  paths:
    - packages/toolkit/          # the published package, wholesale
    - LICENSE                    # required for an open-source repo
    - icon.png

  # Directories whose CONTENTS are copied to the TARGET ROOT with the prefix
  # stripped, so the public repo gets its own README and CI without those
  # files living at the private repo's root:
  #   publish-assets/README.md                      -> README.md
  #   publish-assets/.github/workflows/validate.yml -> .github/workflows/validate.yml
  asset_dirs:
    - publish-assets/

exclude:
  # Hygiene globs applied WITHIN the included set (defense in depth, NOT the
  # privacy boundary). Catches junk riding along inside an included directory.
  patterns:
    - "**/.env"
    - "**/*.env"
    - "**/.DS_Store"
    - "**/__pycache__/"
    - "**/*.pyc"

target:
  repo: example-org/toolkit
  branch: main
```

### Path-matching rules worth pinning down in tests

- `asset_dirs` are matched **before** `include.paths`, so a remap wins over any
  verbatim overlap.
- A trailing `/` on an include path means "this directory and everything under it";
  a path with no trailing slash matches that exact file *or* that directory prefix.
- Anything matching neither returns "not published" — the default must be a plain
  `None`/skip, never an exception that a caller might swallow into "publish it".
- Exclude globs are evaluated on the **destination** path, after remapping.
- Deletions matter: after copying, remove every file in the target working copy that
  the current selection does not contain (skipping `.git/`). Otherwise a path
  dropped from the include list stays public forever.

Each of those five lines is a unit test on the selection function. They are cheap,
they run offline, and they are the only tests that directly protect the boundary.

## Per-target config (the scaling shape)

When a second target appears, split the single config into one file per target and
give the publisher a target argument.

```
publish/
├── toolkit.yml     # -> example-org/toolkit
└── sdk.yml         # -> example-org/sdk
```

```yaml
# publish/sdk.yml
include:
  paths:
    - packages/sdk/
    - LICENSE
  asset_dirs:
    - publish-assets/sdk/     # -> target root
exclude:
  patterns: ["**/.env", "**/__pycache__/"]
target:
  repo: example-org/sdk
  branch: main
artifact:
  kind: package               # what this target IS — see below
```

```bash
publish --target sdk --dry-run    # list destination paths, publish nothing
publish --target sdk              # filter, scan, stage, open the PR
```

Two properties this buys:

1. **Cross-target leakage is structurally impossible.** `packages/toolkit/` is not in
   `sdk.yml`, so no bug in the sdk publish can ship it.
2. **`--dry-run` is per target.** Reviewing "what would go public" is a cheap,
   frequent operation instead of a release-day scramble.

## Artifact-shaped metadata patching

A published tree usually needs one file rewritten so it describes the *public*
artifact rather than the private repo — a package manifest, a plugin/extension
manifest, an index of components.

Patch it with the **same include list** that selected the files, so the metadata and
the tree can never disagree:

```python
def patch_manifest(manifest: dict, include_paths: list[str]) -> dict:
    """Keep only entries whose source path falls under an included path."""
    result = copy.deepcopy(manifest)
    result["components"] = [
        c for c in result["components"]
        if any(
            c["source"].lstrip("./").rstrip("/") == inc.rstrip("/")
            or c["source"].lstrip("./").startswith(inc.rstrip("/") + "/")
            for inc in include_paths
        )
    ]
    return result
```

Deriving the patch from the include list rather than a second hand-maintained
denylist is the point: one source of truth, one thing to forget instead of two.

When you have several targets, `artifact.kind` (or an equivalent per-target field)
selects the patcher. Do not let one target's artifact shape be assumed by the
publisher — that assumption is exactly what blocks the second target from landing.

## Source transforms

Some files are correct in the monorepo and wrong in public. Common cases:

- An internal package-registry/proxy URL pinned in a dependency config or lockfile,
  which an outside contributor cannot reach. Rewrite it to the public registry.
- Internal hostnames or paths in example configs. Replace with placeholders.
- Lockfiles that encode an internal resolver. Either rewrite or exclude them; an
  excluded lockfile lets each consumer resolve their own registry.

Keep transforms **pure functions of (path, content)** so they are unit-testable
without touching git, and apply them during the copy. Match on the exact block you
intend to remove and return the content unchanged when it is absent — a transform
that silently mangles a file it did not recognize is worse than no transform.
