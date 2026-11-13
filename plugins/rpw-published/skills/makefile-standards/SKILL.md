---
name: makefile-standards
description: House standard for a GNU Makefile used as a repo's control surface. Covers `## ` help text and `make help`, `.PHONY` policy, the recipe-size threshold for moving logic to `scripts/`, how a target declares and checks its assumptions, naming and grouping, and passing caller values safely. Use when adding, reviewing, auditing or refactoring a Makefile or make target, or when a recipe grows inline shell or Python, a target silently does nothing, or make swallows an exit code.
---

# Makefile Standards

**A target nobody can find does not exist. A target that silently does nothing is worse
than none.** Recipes for each idiom: [references/idioms.md](references/idioms.md).

## The rules

1. **Help text.** Every rule line carries `## <one line>`: what the target does, the
   variables it needs, and whether it mutates anything. Generate `help` from those lines
   and never hand-maintain a list. One hand list drifted until it showed 81 of 190 targets.
2. **`.PHONY`.** Declare every target that does not build a file `.PHONY`, in its own
   section, not in one shared mega-line. A `.PHONY` name with no rule exits 0 having done
   nothing, so delete the name along with its rule.
3. **When a recipe moves to `scripts/`.** Move it when **any** of these is true:
   - more than **10 physical lines** of logic (comments and one usage guard don't count);
   - a loop, or a conditional beyond the usage guard;
   - an inline interpreter (`python -c`, a heredoc) or any JSON parsing.

   **Why:** you can test a recipe only by spawning make. `$$` doubles every quote, each
   line runs in its own shell, every failure becomes exit 2, and no linter reads a
   recipe. A script can be tested, linted and reused. The target is a thin
   wrapper.
4. **Declare assumptions, then check them.** A target that depends on a branch, a path, a
   CLI, a credential or a remote names that dependency in its comment. It checks it first
   and fails loudly with a `Usage:` or `ERROR:` line, the fix, and exit 2. A target that
   mutates anything is a dry run unless `APPLY=` is truthy, and `APPLY` is parsed by value,
   never by presence. When an assumption stops holding, the target must fail, not go quiet.
5. **Naming and grouping.** Use `<noun>-<verb>` families (`plugin-check`, `plugin-sync`).
   Suffixes carry contracts: `-check` is read-only and exits non-zero on drift, `-test` is
   a member gate, `-install` installs a service, `-poll` runs a scheduled job once. Put
   each family under a `# ---- Title ----` header. Avoid near-collisions
   (`integration-test` vs `test-integration`).
6. **Pass caller values through the environment.** A free-text variable never reaches
   recipe argv as `$(X)`. Write `target: export X_IN := $(value X)` and read `"$$X_IN"`.
   Variables that must be numbers get a digits-only guard.
7. **Exit codes do not survive make.** Make reports every failure as exit 2. Anything a
   caller branches on goes on a stable stdout line (`outcome=…`), and callers read that.
8. **Enumerate gates and delegate members.** A PR reports each command a gate runs, with
   its exit code, never just `make x-test`. A root target for a sub-project is
   `$(MAKE) -C <member> verify`.

## Auditing a Makefile

```bash
uv run --no-project python scripts/makefile_audit.py path/to/Makefile
```

The script is read-only and stdlib-only. It prints one row per target (recipe size,
`.PHONY`, `## `, inline interpreter), then the gap lists, then `outcome=clean`, `gaps` or
`unreadable`. Read that last line, not the exit code. Then:

1. Cross-check the target list against `make -pRrq`.
2. Classify every target as keep, document, fix, move or delete.
3. Name each target whose premise is no longer true, with live evidence.

**Prefer additive fixes.** `.PHONY` and `## ` text change nothing make executes; diff
`make -pRrq` before and after to prove it. A human confirms renames, deletions and
behaviour changes to a shared target first.
