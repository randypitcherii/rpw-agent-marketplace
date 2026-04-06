ROOT_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
COMMANDS_SRC := $(ROOT_DIR)/plugins/rpw-building/commands
CURSOR_COMMANDS_DIR := $(HOME)/.cursor/commands
CLAUDE_COMMANDS_DIR := $(HOME)/.claude/commands
MARKETPLACE_BUMP_SCRIPT := $(ROOT_DIR)/scripts/bump_marketplace_versions.py
RELEASE_LOG_PATH := $(ROOT_DIR)/docs/release-log.md
PRODUCTION_BRANCH ?= production
MERGE_DIFF_RANGE ?= HEAD^..HEAD

# Cursor: all .md command files (unified — no variant splitting)
CURSOR_SOURCE_COMMANDS := $(wildcard $(COMMANDS_SRC)/*.md)
SOURCE_COMMANDS ?= $(CURSOR_SOURCE_COMMANDS)

SHELL := /bin/bash

.PHONY: link link-cursor link-claude adopt-cursor unlink unlink-cursor unlink-claude-build check verify test test-integration lint clean public-release-scan public-release-gate required-stack list repair help bump bump-dry version-bump version-bump-dry-run marketplace-release-dry-run marketplace-release production-merge-helper build-init build-checkpoint build-checkpoint-get build-checkpoint-require build-evidence build-evidence-check build-clear publish-setup publish-dry-run publish-public

help:
	@echo "Targets:"
	@echo "  make link               # Link build command into ~/.cursor/commands"
	@echo "  make link-cursor        # Link into ~/.cursor/commands"
	@echo "  make link-claude        # (no-op) Claude gets /build from rpw-building plugin"
	@echo "  make unlink-claude-build # Remove build.md from ~/.claude/commands (migration)"
	@echo "  make adopt-cursor       # Backup regular files, then link into Cursor"
	@echo "  make unlink             # Remove repo-managed links from Cursor"
	@echo "  make check              # Verify Cursor link status"
	@echo "  make verify             # Run repo validation tests"
	@echo "  make public-release-scan # Scan repo for blocked files and secret-like content"
	@echo "  make public-release-gate # Require explicit confirmation + run public-release-scan"
	@echo "  make required-stack     # Enable the required plugin stack in .claude/settings.local.json"
	@echo "  make publish-setup     # Clone the public repo locally (if not already cloned)"
	@echo "  make publish-dry-run   # Preview what would be published to public repo"
	@echo "  make publish-public    # Publish filtered repo to public GitHub"
	@echo "  make repair             # Rebuild Cursor links (unlink + link)"
	@echo "  make list               # List source commands"
	@echo "  make bump               # Bump all plugin + marketplace versions"
	@echo "  make bump-dry           # Preview version bumps (dry-run)"
	@echo "  make version-bump       # Bump changed plugin versions in marketplace.json"
	@echo "  make version-bump-dry-run # Preview version bumps without writing files"
	@echo "  make marketplace-release-dry-run # Preview release bump changes"
	@echo "  make marketplace-release # Dry-run, verify, then bump + release log entry"
	@echo "  make production-merge-helper # Enforce squash merge and bump versions on production"
	@echo "  make build-init         # Initialize build state (BEAD=<id>)"
	@echo "  make build-checkpoint   # Set a build phase checkpoint (CP=<name>)"
	@echo "  make build-checkpoint-get # Print build state (optional CP=<name>)"
	@echo "  make build-checkpoint-require # Gate on checkpoint (CP=<name>)"
	@echo "  make build-evidence     # Save build evidence (PHASE=<name> DATA='<json>')"
	@echo "  make build-evidence-check # Verify all evidence artifacts present"
	@echo "  make build-clear        # Remove build state and evidence"

link: link-cursor

link-cursor:
	@$(MAKE) _link_dir DEST_DIR="$(CURSOR_COMMANDS_DIR)" SOURCE_COMMANDS="$(CURSOR_SOURCE_COMMANDS)"

link-claude:
	@echo "Claude gets /build from rpw-building plugin (marketplace). No symlink needed."
	@echo "Run 'make unlink-claude-build' to remove any existing build.md from ~/.claude/commands."

unlink-claude-build:
	@dest="$(CLAUDE_COMMANDS_DIR)/build.md"; \
	if [ -e "$$dest" ]; then \
		rm "$$dest" && echo "Removed $$dest"; \
	else \
		echo "No build.md at $$dest"; \
	fi

adopt-cursor:
	@mkdir -p "$(CURSOR_COMMANDS_DIR)"
	@for src in $(CURSOR_SOURCE_COMMANDS); do \
		name=$$(basename "$$src"); \
		dest="$(CURSOR_COMMANDS_DIR)/$$name"; \
		if [ -L "$$dest" ]; then \
			: ; \
		elif [ -e "$$dest" ]; then \
			backup="$$dest.backup.$$(date +%Y%m%d-%H%M%S)"; \
			mv "$$dest" "$$backup"; \
			echo "BACKUP $$dest -> $$backup"; \
		fi; \
	done
	@$(MAKE) link-cursor

_link_dir:
	@mkdir -p "$(DEST_DIR)"
	@for src in $(SOURCE_COMMANDS); do \
		name=$$(basename "$$src"); \
		dest="$(DEST_DIR)/$$name"; \
		if [ -L "$$dest" ]; then \
			target=$$(readlink "$$dest"); \
			if [ "$$target" = "$$src" ]; then \
				echo "OK    $$dest -> $$target"; \
			else \
				rm "$$dest"; \
				ln -s "$$src" "$$dest"; \
				echo "FIXED $$dest -> $$src"; \
			fi; \
		elif [ -e "$$dest" ]; then \
			echo "SKIP  $$dest (exists and is not a symlink)"; \
		else \
			ln -s "$$src" "$$dest"; \
			echo "LINK  $$dest -> $$src"; \
		fi; \
	done

unlink: unlink-cursor

unlink-cursor:
	@$(MAKE) _unlink_dir DEST_DIR="$(CURSOR_COMMANDS_DIR)" SOURCE_COMMANDS="$(CURSOR_SOURCE_COMMANDS)"

_unlink_dir:
	@for src in $(SOURCE_COMMANDS); do \
		name=$$(basename "$$src"); \
		dest="$(DEST_DIR)/$$name"; \
		if [ -L "$$dest" ]; then \
			target=$$(readlink "$$dest"); \
			if [ "$$target" = "$$src" ]; then \
				rm "$$dest"; \
				echo "UNLINK $$dest"; \
			else \
				echo "KEEP   $$dest (points elsewhere: $$target)"; \
			fi; \
		fi; \
	done

check:
	@$(MAKE) _check_dir DEST_DIR="$(CURSOR_COMMANDS_DIR)" LABEL="cursor" SOURCE_COMMANDS="$(CURSOR_SOURCE_COMMANDS)"

verify:
	@uv run --with pyyaml --with pytest python -m unittest tests.test_repo_validations tests.test_bump_marketplace_versions tests.test_enable_required_stack tests.test_public_release_gate tests.test_publish_public tests.test_build_makefile_targets -v
	@STATE_FILE=$$(source .claude/hooks/build-state.sh && _build_state_file 2>/dev/null); \
	if [ -n "$$STATE_FILE" ] && [ -f "$$STATE_FILE" ]; then \
		source .claude/hooks/build-state.sh && build_state_set verify_passed; \
	fi

test: ## Run all tests (alias for verify)
	@$(MAKE) verify

test-integration: ## Run live MCP integration tests (requires credentials in dev.env files)
	@uv run python -m unittest tests.integration.test_gemini_image_mcp tests.integration.test_slack_mcp tests.integration.test_glean_mcp tests.integration.test_jira_mcp tests.integration.test_google_mcp tests.integration.test_google_tasks_mcp tests.integration.test_google_docs_mcp -v

lint: ## Check for linting issues
	@echo "No linter configured"

clean: ## Remove Python cache files
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@find . -name "*.pyc" -delete 2>/dev/null || true
	@echo "Cleaned Python cache files"

public-release-scan:
	@uv run python scripts/public_release_gate.py --repo-root .

public-release-gate:
	@PUBLIC_REPO_RELEASE_CONFIRM="$(PUBLIC_REPO_RELEASE_CONFIRM)" \
		uv run python scripts/public_release_gate.py --repo-root . --require-confirmation

PUBLIC_REPO_TARGET := randypitcherii/rpw-agent-marketplace
PUBLIC_REPO_DIR := .public-repo

publish-setup:
	@if [ -d "$(PUBLIC_REPO_DIR)" ]; then \
		echo "$(PUBLIC_REPO_DIR)/ already exists. Run 'make publish-public' to publish."; \
	else \
		echo "Cloning $(PUBLIC_REPO_TARGET) to $(PUBLIC_REPO_DIR)/..."; \
		git clone "https://github.com/$(PUBLIC_REPO_TARGET).git" "$(PUBLIC_REPO_DIR)"; \
		echo "Done. Run 'make publish-dry-run' to preview, 'make publish-public' to publish."; \
	fi

publish-dry-run:
	@uv run --with pyyaml python scripts/publish_public.py --repo-root . --public-repo $(PUBLIC_REPO_DIR) --dry-run

publish-public:
	@$(MAKE) public-release-scan
	@if [ ! -d "$(PUBLIC_REPO_DIR)" ]; then \
		echo "Cloning $(PUBLIC_REPO_TARGET) to $(PUBLIC_REPO_DIR)/..."; \
		git clone "https://github.com/$(PUBLIC_REPO_TARGET).git" "$(PUBLIC_REPO_DIR)"; \
	fi
	@uv run --with pyyaml python scripts/publish_public.py --repo-root . --public-repo $(PUBLIC_REPO_DIR)

required-stack:
	@uv run python scripts/enable_required_stack.py

bump:
	@uv run python scripts/bump_version.py

bump-dry:
	@uv run python scripts/bump_version.py --dry-run

version-bump:
	@set -- --diff-range "$(MERGE_DIFF_RANGE)"; \
	if [ -n "$(RELEASE_LOG_PATH)" ]; then \
		set -- "$$@" --release-log "$(RELEASE_LOG_PATH)"; \
	fi; \
	if [ -n "$(PR_FIELD)" ]; then \
		set -- "$$@" --pr-field "$(PR_FIELD)"; \
	fi; \
	if [ -n "$(CHECKS_FIELD)" ]; then \
		set -- "$$@" --checks-field "$(CHECKS_FIELD)"; \
	fi; \
	uv run python "$(MARKETPLACE_BUMP_SCRIPT)" "$$@"

version-bump-dry-run:
	@uv run python "$(MARKETPLACE_BUMP_SCRIPT)" --diff-range "$(MERGE_DIFF_RANGE)" --dry-run

marketplace-release-dry-run:
	@$(MAKE) version-bump-dry-run MERGE_DIFF_RANGE="$(MERGE_DIFF_RANGE)"

marketplace-release:
	@if [ -z "$$(git remote)" ]; then \
		echo "No git remote configured; release log PR field will default to 'Unavailable (no remote configured)'."; \
	else \
		echo "Git remote detected; release log PR field defaults to current commit id unless PR_FIELD is provided."; \
	fi
	@$(MAKE) public-release-gate
	@$(MAKE) marketplace-release-dry-run MERGE_DIFF_RANGE="$(MERGE_DIFF_RANGE)"
	@$(MAKE) verify
	@$(MAKE) version-bump MERGE_DIFF_RANGE="$(MERGE_DIFF_RANGE)" RELEASE_LOG_PATH="$(RELEASE_LOG_PATH)" PR_FIELD="$(PR_FIELD)"

production-merge-helper:
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" != "$(PRODUCTION_BRANCH)" ]; then \
		echo "Refusing to run: current branch is '$$branch' (expected '$(PRODUCTION_BRANCH)')"; \
		exit 1; \
	fi; \
	parent_count=$$(git rev-list --parents -n 1 HEAD | awk '{print NF-1}'); \
	if [ "$$parent_count" -ne 1 ]; then \
		echo "Refusing to run: HEAD must be a squash-style commit with exactly one parent."; \
		echo "Found parent count: $$parent_count"; \
		exit 1; \
	fi; \
	echo "Verified squash-style HEAD commit on $(PRODUCTION_BRANCH)."; \
	$(MAKE) verify; \
	$(MAKE) version-bump MERGE_DIFF_RANGE="$(MERGE_DIFF_RANGE)" RELEASE_LOG_PATH="$(RELEASE_LOG_PATH)" PR_FIELD="$(PR_FIELD)"

# ── Build lifecycle wrappers ──────────────────────────────────────────
# Thin wrappers around .claude/hooks/build-state.sh for discoverability
# and correct path resolution in worktrees.

build-init:
	@test -n "$(BEAD)" || { echo "Usage: make build-init BEAD=<id>"; exit 1; }
	@source .claude/hooks/build-state.sh && build_state_init "$(BEAD)"

build-checkpoint:
	@test -n "$(CP)" || { echo "Usage: make build-checkpoint CP=<name>"; exit 1; }
	@source .claude/hooks/build-state.sh && build_state_set "$(CP)"

build-checkpoint-get:
	@source .claude/hooks/build-state.sh && build_state_get $(CP)

build-checkpoint-require:
	@test -n "$(CP)" || { echo "Usage: make build-checkpoint-require CP=<name>"; exit 1; }
	@source .claude/hooks/build-state.sh && build_state_require "$(CP)"

build-evidence:
	@test -n "$(PHASE)" || { echo "Usage: make build-evidence PHASE=<name> DATA='<json>'"; exit 1; }
	@test -n "$(DATA)" || { echo "Usage: make build-evidence PHASE=<name> DATA='<json>'"; exit 1; }
	@source .claude/hooks/build-state.sh && build_evidence_save "$(PHASE)" '$(DATA)'

build-evidence-check:
	@source .claude/hooks/build-state.sh && build_evidence_check

build-clear:
	@source .claude/hooks/build-state.sh && build_state_clear

_check_dir:
	@echo "Checking $(LABEL): $(DEST_DIR)"
	@for src in $(SOURCE_COMMANDS); do \
		name=$$(basename "$$src"); \
		dest="$(DEST_DIR)/$$name"; \
		if [ ! -e "$$dest" ] && [ ! -L "$$dest" ]; then \
			echo "MISSING $$name"; \
		elif [ ! -L "$$dest" ]; then \
			echo "NOT-LINK $$name"; \
		else \
			target=$$(readlink "$$dest"); \
			if [ "$$target" = "$$src" ]; then \
				echo "OK      $$name"; \
			elif [ -e "$$dest" ]; then \
				echo "WRONG   $$name -> $$target"; \
			else \
				echo "BROKEN  $$name -> $$target"; \
			fi; \
		fi; \
	done

repair: unlink link

list:
	@echo "Source commands: $(COMMANDS_SRC)"
	@echo "Cursor sources:" && for f in $(CURSOR_SOURCE_COMMANDS); do echo "  $$f"; done
	@echo ""
	@echo "Cursor commands dir: $(CURSOR_COMMANDS_DIR)"
	@ls -la "$(CURSOR_COMMANDS_DIR)" 2>/dev/null || echo "(missing)"
	@echo ""
	@echo "Claude: /build comes from rpw-building plugin (no symlink). Run 'make unlink-claude-build' to remove any existing link."
