# Per-target publication pipeline

## Sequence

```text
1. SELECT       require one explicit target; never imply "all"
2. PREFLIGHT    clean source checkout at the declared integration commit
3. MATERIALIZE  copy only target include-list content; run approved transforms
4. PROMOTE      create one commit on a PR to published/<target>
5. REPRODUCE    rebuild with trusted integration-branch code
6. VALIDATE     exact tree/hash, paths, secrets, complete-tree semantic scan
7. APPROVE      merge the private promotion PR
8. EXPORT       copy tracked file contents to a temporary artifact directory
9. CLONE        fresh clone of the public target's latest default branch
10. SYNC        reconcile full repository or declared managed roots
11. COMMIT      exactly one target-local commit with one public parent
12. PR          push one target branch, open the public PR, wait for checks, merge
```

## Git boundary

The delivery boundary transfers **file contents only**. It never transfers private Git refs, commits, trees, blobs, metadata, remotes, reflogs, configuration, or commit messages.

Before push, assert:

- the publish commit has exactly one parent;
- that parent equals the fetched public default-branch commit;
- `origin/<default>..HEAD` contains exactly one commit;
- the clone has only its public origin remote;
- no `.git` directory came from the private artifact.

Never use `clone --mirror`, `git bundle`, `fast-export`, a private ref push, subtree history transfer, or `.git` copying.

## Ownership modes

- **Full:** the target definition manages the entire public repository. Delete every target file absent from the approved artifact.
- **Scoped:** the definition lists `managed_paths`. Reconcile and delete only under those roots. Preserve all unrelated target files.

For scoped targets, every include destination must be under a managed root. Use explicit source-to-destination mappings when private source paths and public target paths differ.

## Fail-closed rules

| Failure | Required result |
|---|---|
| Unknown target/config key/transform | Abort before copy |
| Dirty source or wrong source commit | Abort |
| Candidate tree/hash mismatch | Abort |
| Secret or sensitive scanner error | Abort; do not claim success |
| Public default branch moved before preparation | Re-clone/rebase by rebuilding, never force private ancestry |
| Target CI fails | Leave PR unmerged |
| No artifact change | Create no public commit or PR |
| Repeat run | Produce the same artifact hash and a clean no-op |

The private promotion PR is the primary approval boundary. The public PR is a target-local delivery record and can merge automatically after required checks pass.
