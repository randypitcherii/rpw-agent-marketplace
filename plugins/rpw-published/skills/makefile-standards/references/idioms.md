# Makefile idioms, with the failure each one prevents

Each idiom below has been tested in a Makefile with roughly 190 targets. It names the
failure it exists to prevent.

## Generated help

```make
##@ Start here
help: ## List every documented target, grouped by section
	@awk 'BEGIN{FS=":.*## "} /^##@ /{printf "\n%s\n",substr($$0,5);next} /^[a-zA-Z0-9_.-]+:([^=]|$$).*## /{printf "  make %-30s %s\n",$$1,$$2}' $(MAKEFILE_LIST)
```

Make `help` the first rule so that a bare `make` prints it. A `##@ Section` line starts
a group; the awk prints it as a header. `([^=]|$$)` skips `VAR:=` assignments. Never
write `## ` inside the help text itself: the field separator is greedy, so the
description would start after the last marker. **Failure prevented:** a
hand-written echo list that every new target has to remember to update. One list fell
to 81 of 190 targets while the `## ` text on the rule lines stayed complete.

Lock it in with a test that every rule line matching `^[a-z0-9-]+:` carries `## `.

## Section-local `.PHONY`

```make
# ---- Plugin freshness (#902) ----
.PHONY: plugin-freshness plugin-freshness-poll
plugin-freshness: ## Is the installed copy current? [JSON=1]
	@uv run python scripts/plugin_freshness.py report
```

**Failure prevented:** a missing `.PHONY` breaks the day a file or directory with the
target's name appears, because make then reports the target "up to date" and runs
nothing. One shared 90-name `.PHONY` line also turns into a merge-conflict magnet for
parallel workers.

## Usage guard and loud assumption check

```make
publish-promote: ## Open a promotion PR (TARGET=<slug> DESCRIPTION=<text>; release branch only)
	@test "$$(git rev-parse --abbrev-ref HEAD)" = "$(RELEASE_BRANCH)" || { \
	  echo "ERROR: run from $(RELEASE_BRANCH)" >&2; exit 2; }
	@test -n "$(TARGET)" || { echo "Usage: make publish-promote TARGET=<slug> DESCRIPTION=<text>" >&2; exit 2; }
	@uv run python scripts/publish.py promote ...
```

Check the assumption before any side effect. Print a `Usage:` or `ERROR:` line with the
fix, then exit 2. **Failure prevented:** a target that silently assumed a local-directory
install kept "working" after the install moved to a remote source. It bumped and
committed in a checkout that nothing read.

## Opaque value transport

```make
spawn: export SPAWN_TITLE := $(value TITLE)
spawn: ## Spawn a worker (TITLE="<free text>")
	@uv run python scripts/spawn.py --title "$$SPAWN_TITLE"
```

`$(value X)` takes the variable's text without expanding it. `:=` stores that text
without expanding it again, and `export` hands it to the recipe's environment, where the
shell does no parsing. `"$$SPAWN_TITLE"` is a single expansion that the shell never
re-parses. **Failure prevented:** `$(TITLE)` pasted into a recipe line is *syntax*. A
backtick in a PR title ran, a `;` started a second command, and a `"` closed the quote.

A word-split escape hatch (`SPAWN_ARGS='--dry-run --x'`) may be interpolated on purpose.
It must be author-controlled and is never transported automatically.

## Digit guards

```make
require-digits = case "$(2)" in ''|*[!0-9]*) printf '%s\n' "make: $(1)= must be digits; got: $(2)" >&2; exit 2;; esac
claim:
	@$(call require-digits,ISSUE,$$ISSUE_IN); uv run python scripts/claim.py "$$ISSUE_IN"
```

Pass a shell variable *reference* (`$$ISSUE_IN`) so the value is never re-parsed.
**Failure prevented:** `ISSUE='1 --repo other/x'` flowing on to `gh`.

## APPLY by value

```make
APPLY_TRUTHY := 1 true yes on
APPLY_FALSY  := 0 false no off
APPLY_FLAG = $(if $(filter $(APPLY_TRUTHY),$(APPLY)),--apply,)
apply-value-check: ## Internal: refuse an APPLY= that is neither truthy nor falsy
	@if [ -n "$(strip $(APPLY))" ] && [ -z "$(filter $(APPLY_TRUTHY) $(APPLY_FALSY),$(APPLY))" ]; then \
	  echo "APPLY= is not a recognised value; use one of: $(APPLY_TRUTHY) $(APPLY_FALSY)" >&2; exit 2; fi
sync: apply-value-check ## Sync installed copies (dry run unless APPLY=1)
	@uv run python scripts/sync.py $(APPLY_FLAG)
```

**Failure prevented:** `$(if $(APPLY),--apply,)` tests for a non-empty value, not the
value itself, so `APPLY=0` *applied*. An unrecognised value is refused, because a silent
downgrade to a dry run is just as dangerous: the operator believes the rollback landed.

## Verdicts on stdout, not in the exit code

GNU make reports every non-zero recipe status as its own exit 2:
`printf 'x:\n\t@exit 4\n' | make -f - x; echo $?` prints `2`. A script whose 3 and 4 mean
different things loses that distinction behind make. Print a stable last line
(`outcome=clean|survivors|unprovable`, `relation=sibling|foreign`), document it next to
the target, and have callers parse it. Treat the exit code through make as yes/no only.

## Parallel fan-out over independent suites

```make
.PHONY: suites suite-a suite-b
suites: suite-a suite-b
gate:
	@$(MAKE) -j 8 --no-print-directory -k suites
```

`-k` keeps going after the first failure, so one run reports every red suite. Each
`suite-*` stays a named target that you can run on its own.

## Member delegation and enumerated gates

```make
app-test: ## App member gate: pytest + ruff
	@cd projects/app && $(MAKE) verify
```

The member's own Makefile owns its commands. A PR that cites `make app-test` still lists
every command it hides, with an exit code for each (`pytest -q` → 0,
`ruff check .` → 0, `ruff format --check .` → 0). **Failure prevented:** a PR reported a
wrapper green after running only its pytest half, and CI then failed on formatting.

## Proving a Makefile edit is behaviour-neutral

```bash
git show HEAD:Makefile > /tmp/base.mk
diff <(make -pRrq -f /tmp/base.mk : 2>/dev/null | grep -v '^#' | sort) \
     <(make -pRrq -f Makefile    : 2>/dev/null | grep -v '^#' | sort)
```

Make strips `## ` comments before building its database. A help-text-only edit should
therefore diff to nothing, and a `.PHONY` addition to that one line.
