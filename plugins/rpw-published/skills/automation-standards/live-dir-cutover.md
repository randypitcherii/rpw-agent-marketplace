# Live-directory cutover

Companion to [SKILL.md](SKILL.md). Use it whenever a directory that a running service
reads or writes is renamed or moved — `git mv`, a repo restructure, a checkout of a
branch that did either.

**A checkout moves tracked files only.** `git mv` in the tree that makes the rename
carries everything, because it renames the directory — but every *other* checkout that
pulls the rename (the live deploy clone, a sibling worktree) moves only what git tracks.
A live-service tree also holds state git never sees: `.env` files, SQLite databases,
`node_modules`, build output, caches. After the pull, that state is still at the old
path, and the old directory *looks* like leftovers. Treating it as leftovers once destroyed a service's only database (#882): an
inventory with `find -maxdepth 3` missed a database at depth 4, and the `rm -rf` of the
old directory ran in the same command as the inspection that first showed it.
Unrecoverable — no backup, no snapshot, no open file descriptor.

## The procedure

Run it in each live checkout, before and after pulling the rename. Stop the service
first, so nothing writes to either path mid-move. `$OLD` is the pre-rename directory,
`$NEW` its destination.

1. **Inventory at unbounded depth, ignored files included.** Never pass `-maxdepth`.
   ```bash
   git -C "$OLD" ls-files --others            # untracked, INCLUDING ignored
   comm -13 <(git -C "$OLD" ls-files | sort) \
            <(cd "$OLD" && find . ! -type d -not -path './.git/*' | sed 's|^\./||' | sort)
   ```
   The two lists must agree; the `find` cross-check also covers a directory git no
   longer tracks at all. `ls-files --others --exclude-standard` alone is **not** an
   inventory: it hides every file an ignore rule still matches (`.env`, `*.db` patterns
   usually do), and those are exactly the state that matters.
2. **Migrate every listed path, then verify each one at `$NEW`** (`cmp`, or size +
   checksum for large files). Regenerable output (`node_modules`, build dirs, caches)
   may be rebuilt instead of moved — decide per path, and say which.
3. **Re-run the step 1 inventory against `$OLD` as its own command.** Read it. Anything
   still listed is unmigrated, not leftover.
4. **Delete only what is empty, in a separate command.**
   `find "$OLD" -depth -type d -empty -delete` removes empty directories and nothing else;
   if `$OLD` itself survives, step 3 was wrong.

**Never chain a delete onto the inspection that justifies it.** `ls … && rm -rf …` or
`find …; rm -rf …` decides before anyone has read the output. `rm -rf` on a live-service
path is never part of this procedure.

The systemic fix is keeping production state outside the source tree, so no tree-level
operation can reach it; this procedure is the guard for every tree where that has not
happened yet.
