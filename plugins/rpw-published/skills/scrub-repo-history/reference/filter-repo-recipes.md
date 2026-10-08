# git-filter-repo recipes

Everything below assumes the gate in `SKILL.md` has been followed: rotation done (if a leak),
backup mirror taken, preview shown, rewrite approved.

Every `git filter-repo …` command works as `uvx --from git-filter-repo git-filter-repo …` when the
tool is not installed. Inside a repo where it *is* installed, `git filter-repo` (subcommand form)
is identical.

## 0. Work on a fresh mirror clone

filter-repo refuses to run on a repo that isn't a fresh clone unless you pass `--force`, because a
rewrite is unrecoverable without a pristine copy. Respect that — do not reach for `--force` to make
the warning go away.

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
git clone --mirror /path/to/repo "/tmp/scrub-backup-$STAMP.git"   # THE BACKUP — do not touch it
git clone --mirror /path/to/repo "/tmp/scrub-work-$STAMP.git"     # the working copy
cd "/tmp/scrub-work-$STAMP.git"
```

A `--mirror` clone carries every branch, tag, and note, so a rewrite here covers all of history
rather than just the checked-out branch. filter-repo removes the `origin` remote after rewriting,
deliberately, so an absent-minded `git push` can't fire.

Verify the backup is real before continuing:

```bash
git -C "/tmp/scrub-backup-$STAMP.git" rev-list --all --count   # non-zero == a usable backup
```

## 1. Remove a path from all history

```bash
git filter-repo --path config/prod.env --invert-paths
git filter-repo --path-glob '**/*.pem' --invert-paths
git filter-repo --path-regex '^secrets/.*' --invert-paths
```

`--invert-paths` inverts the selection: keep everything *except* these. Without it, filter-repo
keeps *only* the named paths — a much more destructive mistake that is easy to make in a hurry.

Multiple paths in one pass:

```bash
git filter-repo --invert-paths --path config/prod.env --path deploy/key.pem
```

## 2. Remove content, keep the file

When the file must survive but a value inside it must not (a key in a config that is still in use):

```bash
cat > /tmp/replacements.txt <<'EOF'
PLACEHOLDER-LEAKED-VALUE==>REDACTED
regex:tok_[A-Za-z0-9]{24}==>REDACTED
literal:hunter2==>REDACTED
EOF

git filter-repo --replace-text /tmp/replacements.txt
```

Rules are one per line, `old==>new`, default literal; prefix `regex:` or `glob:` to change that.
Omitting `==>new` replaces with `***REMOVED***`. **The replacements file itself now contains the
secret** — write it outside the repo and delete it afterwards.

`--replace-text` rewrites blob contents, so it also catches the secret in files you didn't think to
name — which is exactly why the preview should search by pattern, not just by path.

## 3. Strip large blobs

```bash
git filter-repo --strip-blobs-bigger-than 10M
```

Independent of path selection; useful when the scrub is about repo size rather than secrecy.

## 4. Verify

```bash
git log --all --oneline -- config/prod.env          # must print nothing
git rev-list --objects --all | grep config/prod.env # must print nothing
git grep -I -n 'PLACEHOLDER-LEAKED-VALUE' $(git rev-list --all) -- 2>/dev/null | head   # must print nothing
git log --all --oneline | wc -l                     # commit count: expect the same, minus none
git for-each-ref refs/tags                          # tags now point at rewritten SHAs
```

The commit count should be *unchanged* for a path removal — filter-repo rewrites commits rather
than dropping them, unless a commit becomes empty (add `--prune-empty=never` to keep those).

Then confirm the intended content still exists:

```bash
git log --all --oneline -- src/            # unaffected history intact
git cat-file -p HEAD:README.md | head       # a known-good file still readable
```

## 5. Push back

Only after the second confirmation (see `scripts/scrub_force_push.sh`):

```bash
git remote add origin <url>
git push --force --all origin
git push --force --tags origin
```

`--mirror` push (`git push --mirror origin`) also deletes remote refs that no longer exist locally.
That is occasionally what you want and frequently a disaster — prefer the explicit `--all` +
`--tags` pair unless deleting stale remote refs is an approved part of the plan.

If a stale tag survives on the remote, delete it explicitly:

```bash
git push origin :refs/tags/<tag>
```

## 6. Local cleanup

On every machine that had the old objects (including the machine that did the rewrite):

```bash
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

This is local only. On a GitHub-hosted remote, unreferenced objects stay reachable by SHA until
GitHub garbage-collects them; ask GitHub Support to run a GC on the repository and its fork network
if the content is genuinely sensitive.

## Common failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `Refusing to destructively overwrite repo history` | Not a fresh clone | Re-clone (`--mirror`); don't reach for `--force` |
| Everything deleted except the target | `--path` without `--invert-paths` | Restore from the backup mirror and re-run |
| Content still in `git log --all` | Rewrote one branch, not the mirror | Rewrite the `--mirror` clone so all refs are processed |
| Content returns after a fetch | A stale remote tag or branch still points at old history | Delete the remote ref, then re-push |
| `git: 'filter-repo' is not a git command` | Not installed | `uvx --from git-filter-repo git-filter-repo …` |
| Rewrite is enormous / slow on a huge repo | Repo size | BFG (`--delete-files`, `--replace-text`) is faster but less precise; the gate is unchanged |
