"""Repository validation tests for marketplace-first layout."""

import json
import os
import re
import unittest

CALENDAR_VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}\d{2}$")


def _repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _marketplace_path():
    return os.path.join(_repo_root(), ".claude-plugin", "marketplace.json")


def _mcp_json_paths(root):
    """Return paths to .mcp.json and .reference.json files under plugins with MCP servers."""
    paths = []
    for plugin_name in ["rpw-working", "rpw-building"]:
        plugin_root = os.path.join(root, "plugins", plugin_name)
        top_mcp = os.path.join(plugin_root, ".mcp.json")
        if os.path.isfile(top_mcp):
            paths.append(top_mcp)
        mcp_dir = os.path.join(plugin_root, "mcp-servers")
        if not os.path.isdir(mcp_dir):
            continue
        for name in os.listdir(mcp_dir):
            subdir = os.path.join(mcp_dir, name)
            if not os.path.isdir(subdir):
                continue
            for f in os.listdir(subdir):
                if f.endswith(".mcp.json") or f.endswith(".reference.json"):
                    paths.append(os.path.join(subdir, f))
    return paths


def _resolve_plugin_source(root, plugin_root, source):
    """Resolve marketplace plugin source path with support for explicit root-relative sources."""
    if source.startswith("./plugins/"):
        return os.path.normpath(os.path.join(root, source))
    return os.path.normpath(os.path.join(root, plugin_root, source))


class TestMarketplaceLayout(unittest.TestCase):
    def _load_marketplace(self):
        with open(_marketplace_path()) as f:
            return json.load(f)

    def test_marketplace_exists(self):
        self.assertTrue(os.path.isfile(_marketplace_path()), "marketplace file must exist")

    def test_metadata_plugin_root_is_plugins(self):
        d = self._load_marketplace()
        self.assertEqual(
            d.get("metadata", {}).get("pluginRoot"),
            "./plugins",
            "metadata.pluginRoot must be './plugins' for marketplace-first layout",
        )

    def test_marketplace_sources_resolve_to_existing_plugin_dirs(self):
        root = _repo_root()
        d = self._load_marketplace()
        plugin_root = d.get("metadata", {}).get("pluginRoot", "")
        self.assertTrue(plugin_root, "metadata.pluginRoot must be set")
        base = os.path.normpath(os.path.join(root, plugin_root))
        self.assertTrue(os.path.isdir(base), f"pluginRoot dir must exist: {base}")
        for p in d.get("plugins", []):
            source = p.get("source", "")
            self.assertTrue(source, f"plugin {p.get('name')} must have source")
            resolved = _resolve_plugin_source(root, plugin_root, source)
            self.assertTrue(
                os.path.isdir(resolved),
                f"plugin source must resolve to existing dir: {source} -> {resolved}",
            )

    def test_marketplace_name_is_rpw_agent_marketplace(self):
        d = self._load_marketplace()
        self.assertEqual(d.get("name"), "rpw-agent-marketplace")

    def test_marketplace_plugins_present(self):
        d = self._load_marketplace()
        names = {p.get("name", "") for p in d.get("plugins", [])}
        self.assertIn("rpw-building", names)
        self.assertIn("rpw-working", names)
        self.assertIn("rpw-databricks", names)
        self.assertFalse({"rpw-agent-assets", "rpw-fe-uco-management"} & names)

    def test_marketplace_plugin_sources_have_plugin_manifests(self):
        root = _repo_root()
        d = self._load_marketplace()
        plugin_root = d.get("metadata", {}).get("pluginRoot", "")
        self.assertTrue(plugin_root.startswith("./"), "metadata.pluginRoot should be a relative path")
        for p in d.get("plugins", []):
            name = p.get("name", "")
            source = p.get("source", "")
            self.assertTrue(source and ".." not in source, f"invalid source for {name}: {source}")
            plugin_dir = _resolve_plugin_source(root, plugin_root, source)
            manifest = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
            self.assertTrue(os.path.isdir(plugin_dir), f"plugin dir missing for {name}: {plugin_dir}")
            self.assertTrue(os.path.isfile(manifest), f"plugin manifest missing for {name}: {manifest}")
            with open(manifest) as f:
                plugin_manifest = json.load(f)
            self.assertEqual(plugin_manifest.get("name"), name, f"manifest name mismatch for {name}")
            self.assertIn(
                "version",
                plugin_manifest,
                f"plugin manifest for {name} must define a version field",
            )

    def test_plugin_json_versions_match_marketplace(self):
        root = _repo_root()
        d = self._load_marketplace()
        plugin_root = d.get("metadata", {}).get("pluginRoot", "")
        for p in d.get("plugins", []):
            name = p.get("name", "")
            marketplace_version = p.get("version", "")
            plugin_dir = _resolve_plugin_source(root, plugin_root, p.get("source", ""))
            manifest = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
            with open(manifest) as f:
                plugin_manifest = json.load(f)
            self.assertEqual(
                plugin_manifest.get("version"),
                marketplace_version,
                f"plugin.json version for {name} must match marketplace.json version",
            )

    def test_marketplace_plugin_versions_use_calendar_format(self):
        d = self._load_marketplace()
        for p in d.get("plugins", []):
            version = p.get("version", "")
            self.assertTrue(version, f"plugin {p.get('name')} must define version in marketplace.json")
            self.assertRegex(
                version,
                CALENDAR_VERSION_RE,
                f"plugin {p.get('name')} version must match YYYY.MM.DDNN, got: {version}",
            )

    def test_marketplace_metadata_version_uses_calendar_format(self):
        d = self._load_marketplace()
        version = d.get("metadata", {}).get("version", "")
        self.assertTrue(version, "metadata.version must be set")
        self.assertRegex(
            version,
            CALENDAR_VERSION_RE,
            f"metadata.version must match YYYY.MM.DDNN, got: {version}",
        )

    def test_no_root_plugin_manifest(self):
        root = _repo_root()
        path = os.path.join(root, ".claude-plugin", "plugin.json")
        self.assertFalse(os.path.isfile(path), "root should be marketplace-only (no .claude-plugin/plugin.json)")


class TestMarketplacePlugins(unittest.TestCase):
    def _rpw_building_command_filenames(self):
        root = _repo_root()
        commands_dir = os.path.join(root, "plugins", "rpw-building", "commands")
        return [name for name in os.listdir(commands_dir) if name.endswith(".md")]

    def test_working_plugin_has_uco_management_skill(self):
        root = _repo_root()
        path = os.path.join(root, "plugins/rpw-working/skills/uco-management/SKILL.md")
        self.assertTrue(os.path.isfile(path))

    def test_building_plugin_has_required_skills(self):
        root = _repo_root()
        for skill in ["randy_mcp_standards", "mcp-env-setup", "auto-dispatch"]:
            path = os.path.join(root, f"plugins/rpw-building/skills/{skill}/SKILL.md")
            self.assertTrue(os.path.isfile(path), f"building plugin must have skill: {skill}")

    def test_building_plugin_has_commands(self):
        root = _repo_root()
        plugin_root = os.path.join(root, "plugins", "rpw-building")
        self.assertTrue(os.path.isfile(os.path.join(plugin_root, "commands", "build.md")))

    def test_databricks_plugin_has_mvp_components(self):
        root = _repo_root()
        plugin_root = os.path.join(root, "plugins", "rpw-databricks")
        self.assertTrue(os.path.isfile(os.path.join(plugin_root, ".claude-plugin", "plugin.json")))
        self.assertTrue(os.path.isfile(os.path.join(plugin_root, "commands", "databricks-workflow.md")))
        self.assertTrue(
            os.path.isfile(
                os.path.join(plugin_root, "skills", "databricks-work-activities", "SKILL.md")
            )
        )

    def test_context_mode_activity_pattern_assets_exist(self):
        """Repository should include a durable context-mode activity pattern and command."""
        root = _repo_root()
        command_path = os.path.join(root, "plugins", "rpw-building", "commands", "activity-context.md")
        process_doc_path = os.path.join(root, "docs", "process", "context-mode-activity-pattern.md")

        self.assertTrue(os.path.isfile(command_path), "activity-context command must exist")
        self.assertTrue(os.path.isfile(process_doc_path), "context-mode activity process doc must exist")

        with open(command_path) as f:
            command_content = f.read()
        self.assertIn("/activity-context", command_content)
        self.assertIn("Process with context mode tools.", command_content)
        self.assertIn("Top 3-5 signals", command_content)

        with open(process_doc_path) as f:
            process_content = f.read()
        self.assertIn("Context Mode Activity Pattern", process_content)
        self.assertIn("Minimum output contract", process_content)

    def test_required_stack_assets_enforce_single_onboarding_mode(self):
        """Required dependency onboarding should be one fixed stack without profile branching."""
        root = _repo_root()
        command_path = os.path.join(root, "plugins", "rpw-building", "commands", "required-stack.md")
        process_doc_path = os.path.join(root, "docs", "process", "required-plugin-stack.md")

        self.assertTrue(os.path.isfile(command_path), "required-stack command must exist")
        self.assertTrue(os.path.isfile(process_doc_path), "required-plugin-stack process doc must exist")

        with open(command_path) as f:
            command_content = f.read()
        self.assertIn("/required-stack", command_content)
        self.assertIn("one onboarding mode only", command_content)
        self.assertIn("Do not offer persona-based variants", command_content)

        with open(process_doc_path) as f:
            process_content = f.read()
        self.assertIn("single onboarding model", process_content)
        self.assertIn("Do not provide profile selection", process_content)

    def test_no_claude_variant_files_exist(self):
        """Commands are unified — no .claude.md variant files should exist."""
        command_filenames = self._rpw_building_command_filenames()
        claude_variants = [name for name in command_filenames if name.endswith(".claude.md")]
        self.assertEqual(
            claude_variants,
            [],
            f"No .claude.md variant files should exist (found: {claude_variants})",
        )

    def test_working_plugin_has_mcp_servers(self):
        root = _repo_root()
        plugin_root = os.path.join(root, "plugins", "rpw-working")
        self.assertTrue(os.path.isfile(os.path.join(plugin_root, ".mcp.json")))
        for server in ["google-tasks", "google-docs-with-subtabs"]:
            server_root = os.path.join(plugin_root, "mcp-servers", server)
            for required in ["pyproject.toml", "run_mcp.py", "mcp_server.py", "README.md"]:
                self.assertTrue(
                    os.path.isfile(os.path.join(server_root, required)),
                    f"missing {required} for {server}",
                )

    def test_building_plugin_has_mcp_servers(self):
        root = _repo_root()
        plugin_root = os.path.join(root, "plugins", "rpw-building")
        self.assertTrue(os.path.isfile(os.path.join(plugin_root, ".mcp.json")))
        # chrome-devtools uses a shell wrapper (run_mcp.sh), not Python
        chrome_root = os.path.join(plugin_root, "mcp-servers", "chrome-devtools")
        self.assertTrue(
            os.path.isfile(os.path.join(chrome_root, "run_mcp.sh")),
            "missing run_mcp.sh for chrome-devtools",
        )

    def test_rpw_building_mcp_servers_follow_standards(self):
        """rpw-building MCP servers (if any) must follow the same standards as rpw-working."""
        root = _repo_root()
        manifest_path = os.path.join(root, "plugins", "rpw-building", ".claude-plugin", "plugin.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        mcp_rel = manifest.get("mcpServers")
        if mcp_rel is None:
            return  # no MCP servers declared — that's fine
        plugin_root = os.path.join(root, "plugins", "rpw-building")
        mcp_path = os.path.join(plugin_root, mcp_rel)
        if os.path.isdir(mcp_path):
            # Directory format: each subdirectory is an MCP server
            for server in os.listdir(mcp_path):
                server_root = os.path.join(mcp_path, server)
                if not os.path.isdir(server_root):
                    continue
                if server == "lib":
                    continue  # shared library, not a server
                # Shell-based servers (e.g. chrome-devtools) use run_mcp.sh
                if os.path.isfile(os.path.join(server_root, "run_mcp.sh")):
                    continue
                for required in ("run_mcp.py", "pyproject.toml"):
                    self.assertTrue(
                        os.path.isfile(os.path.join(server_root, required)),
                        f"missing {required} for rpw-building MCP server {server}",
                    )
        elif os.path.isfile(mcp_path):
            # File format: JSON file referencing MCP servers
            with open(mcp_path) as f:
                mcp_config = json.load(f)
            self.assertIn("mcpServers", mcp_config,
                          f"MCP config file {mcp_rel} missing 'mcpServers' key")
        else:
            self.fail(f"mcpServers path {mcp_rel} does not exist")

    def test_rpw_working_manifest_declares_mcp_servers_to_mcp_json(self):
        root = _repo_root()
        manifest_path = os.path.join(root, "plugins", "rpw-working", ".claude-plugin", "plugin.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        self.assertIn("mcpServers", manifest, "rpw-working must declare mcpServers")
        self.assertEqual(
            manifest.get("mcpServers"),
            "./.mcp.json",
            "rpw-working mcpServers must point to ./.mcp.json",
        )

    def test_rpw_building_manifest_declares_mcp_servers_to_mcp_json(self):
        root = _repo_root()
        manifest_path = os.path.join(root, "plugins", "rpw-building", ".claude-plugin", "plugin.json")
        with open(manifest_path) as f:
            manifest = json.load(f)
        self.assertIn("mcpServers", manifest, "rpw-building must declare mcpServers")
        self.assertEqual(
            manifest.get("mcpServers"),
            "./.mcp.json",
            "rpw-building mcpServers must point to ./.mcp.json",
        )

    def test_work_backlog_includes_human_language(self):
        root = _repo_root()
        path = os.path.join(root, "plugins", "rpw-working", "skills", "work-backlog", "SKILL.md")
        self.assertTrue(os.path.isfile(path), "work-backlog skill must exist")
        with open(path) as f:
            content = f.read()
        self.assertIn(
            "HUMAN",
            content,
            "work-backlog skill must include HUMAN ownership language",
        )

    def _all_plugin_manifests(self):
        """Return list of (plugin_name, manifest_dict, plugin_dir) for all plugins."""
        root = _repo_root()
        with open(_marketplace_path()) as f:
            marketplace = json.load(f)
        plugin_root = marketplace.get("metadata", {}).get("pluginRoot", "")
        results = []
        for p in marketplace.get("plugins", []):
            name = p.get("name", "")
            source = p.get("source", "")
            plugin_dir = _resolve_plugin_source(root, plugin_root, source)
            manifest_path = os.path.join(plugin_dir, ".claude-plugin", "plugin.json")
            if os.path.isfile(manifest_path):
                with open(manifest_path) as f:
                    manifest = json.load(f)
                results.append((name, manifest, plugin_dir))
        return results

    def test_mcp_servers_is_never_a_directory_path(self):
        """mcpServers must point to a .json file, not a directory. Directory paths silently break plugins."""
        for name, manifest, _plugin_dir in self._all_plugin_manifests():
            mcp = manifest.get("mcpServers")
            if mcp is None:
                continue
            if isinstance(mcp, str):
                self.assertTrue(
                    mcp.endswith(".json"),
                    f"plugin {name}: mcpServers is '{mcp}' — must end in .json (file path), "
                    f"not '/' (directory path). Directory paths silently break the entire plugin.",
                )
                self.assertFalse(
                    mcp.endswith("/"),
                    f"plugin {name}: mcpServers is '{mcp}' — directory paths silently break plugins.",
                )

    def test_plugin_json_has_no_unrecognized_fields(self):
        """plugin.json must only contain recognized Claude Code manifest fields."""
        recognized_fields = {
            "name", "version", "description", "author",
            "skills", "commands", "hooks", "agents", "mcpServers",
        }
        for name, manifest, _plugin_dir in self._all_plugin_manifests():
            unrecognized = set(manifest.keys()) - recognized_fields
            self.assertEqual(
                unrecognized,
                set(),
                f"plugin {name} has unrecognized fields in plugin.json: {unrecognized}. "
                f"Only {sorted(recognized_fields)} are recognized by Claude Code.",
            )

    def test_code_mode_exists_with_safety_checks(self):
        """code-mode.md must exist with safety checks."""
        root = _repo_root()
        path = os.path.join(root, "plugins", "rpw-building", "commands", "code-mode.md")
        self.assertTrue(os.path.isfile(path), "code-mode.md must exist")
        with open(path) as f:
            content = f.read()
        self.assertIn("## Safety Checks", content, "code-mode.md must have Safety Checks section")
        self.assertIn("## Execution Steps", content, "code-mode.md must have Execution Steps section")

    def test_mcp_servers_json_file_has_valid_structure(self):
        """If mcpServers points to a .json file, that file must contain a 'mcpServers' key."""
        for name, manifest, plugin_dir in self._all_plugin_manifests():
            mcp = manifest.get("mcpServers")
            if mcp is None or not isinstance(mcp, str) or not mcp.endswith(".json"):
                continue
            mcp_path = os.path.normpath(os.path.join(plugin_dir, mcp))
            self.assertTrue(
                os.path.isfile(mcp_path),
                f"plugin {name}: mcpServers references '{mcp}' but file does not exist at {mcp_path}",
            )
            with open(mcp_path) as f:
                mcp_config = json.load(f)
            self.assertIn(
                "mcpServers",
                mcp_config,
                f"plugin {name}: MCP config file '{mcp}' must contain a 'mcpServers' key "
                f"with server definitions.",
            )


class TestBuildCommand(unittest.TestCase):
    """Validate build.md structure, sections, and ordering constraints."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        cls.commands_dir = os.path.join(root, "plugins", "rpw-building", "commands")
        cls.build_md = os.path.join(cls.commands_dir, "build.md")
        with open(cls.build_md) as f:
            cls.content = f.read()

    def test_exists_with_autonomous_execution(self):
        self.assertTrue(os.path.isfile(self.build_md))
        self.assertIn("AUTONOMOUS EXECUTION", self.content)
        self.assertFalse(
            os.path.isfile(os.path.join(self.commands_dir, "build.claude.md")),
            "build.claude.md must not exist (merged into build.md)",
        )

    def test_invocation_patterns(self):
        self.assertIn("## Invocation Patterns", self.content)
        self.assertIn("/build <request>", self.content)
        self.assertIn("/build without planning: <request>", self.content)

    def test_safety_eligibility_and_fallback(self):
        self.assertIn("## Autonomous Safety Eligibility Checklist", self.content)
        self.assertIn("Falls back to full planning if safety eligibility fails", self.content)
        self.assertIn("If any item is false, use Full Planning Mode.", self.content)

    def test_branch_naming_convention(self):
        self.assertIn("Branch Naming Convention", self.content)
        self.assertIn("feat/", self.content)
        self.assertIn("bead-id", self.content)

    def test_required_sections_present(self):
        """build.md must have all key structural sections."""
        for section in [
            "Task Worktrees",
            "Failure Handling",
            "Merge Conflict",
            "Worktree Cleanup",
            "Build Standards Enforcement",
            "Code Simplification",
            "Model selection",
            "max depth = 1",
        ]:
            self.assertIn(section, self.content, f"build.md must contain: {section}")

    def test_no_deprecated_content(self):
        self.assertNotIn("GATE 1", self.content, "GATE 1 removed in Wave 2")
        self.assertNotIn("GATE 2", self.content, "GATE 2 removed in Wave 2")
        self.assertNotIn("Implementer Worktrees", self.content, "old terminology")

    def test_retrospective_before_pr_creation(self):
        retro_pos = self.content.find("Post-Build Retrospective")
        pr_pos = self.content.find("PR Creation")
        self.assertGreater(retro_pos, -1)
        self.assertGreater(pr_pos, -1)
        self.assertLess(retro_pos, pr_pos, "Retrospective must come before PR Creation")
        self.assertIn("Categorized recommendations", self.content)

    def test_retrospective_has_categorized_feedback(self):
        """Retro must categorize feedback into project, global, and marketplace."""
        self.assertIn("Project learnings", self.content)
        self.assertIn("Global preferences", self.content)
        self.assertIn("Marketplace feedback", self.content)

    def test_retrospective_requires_evidence_artifact(self):
        """Retro must require a retro.json evidence artifact."""
        self.assertIn("retro.json", self.content)
        # Accept either the Makefile-target form or the shell-sourcing form
        has_evidence = (
            "make build-evidence PHASE=retro" in self.content
            or "build_evidence_save retro" in self.content
        )
        self.assertTrue(has_evidence, "Retro phase must save a retro evidence artifact")

    def test_version_bump_before_pr(self):
        """make bump must appear in Phase 5 before PR creation."""
        bump_pos = self.content.find("make bump")
        pr_pos = self.content.find("PR Creation")
        self.assertGreater(bump_pos, -1, "Phase 5 must include make bump")
        self.assertGreater(pr_pos, -1)
        self.assertLess(bump_pos, pr_pos, "Version bump must come before PR creation")

    def test_build_state_init_before_enter_worktree(self):
        """build-init (or build_state_init) must happen before EnterWorktree in Phase 1 Actions."""
        phase1_start = self.content.find("### Phase 1 Actions")
        self.assertGreater(phase1_start, -1)
        phase1_section = self.content[phase1_start:]
        next_section = phase1_section.find("\n---")
        if next_section > 0:
            phase1_section = phase1_section[:next_section]
        # Accept either the Makefile-target form or the shell-sourcing form
        init_pos = phase1_section.find("build-init")
        if init_pos == -1:
            init_pos = phase1_section.find("build_state_init")
        worktree_pos = phase1_section.find("EnterWorktree")
        self.assertGreater(init_pos, -1, "Phase 1 Actions must reference build-init or build_state_init")
        self.assertGreater(worktree_pos, -1)
        self.assertLess(init_pos, worktree_pos, "build-init must come before EnterWorktree")

    def test_never_ask_ready_at_transitions(self):
        """build.md must instruct agents to never ask 'ready?' at transitions."""
        self.assertIn("never ask", self.content.lower())
        # Must mention this applies to sub-skills too
        self.assertIn("sub-skill", self.content.lower())

    def test_agent_autonomy_never_ask_user_to_run(self):
        """build.md must instruct agents to run everything themselves."""
        lower = self.content.lower()
        self.assertTrue(
            "never ask the user to run" in lower
            or "never tell the user to run" in lower
            or "never ask user to run" in lower,
            "build.md must instruct agents to never ask users to run things",
        )

    def test_tdd_red_green_enforcement(self):
        """build.md must enforce red-green TDD and full-path verification."""
        self.assertIn("red-green", self.content.lower())
        self.assertIn("full-path verification", self.content.lower())

    def test_pre_delivery_gate_blocks_pr(self):
        """PR creation must be explicitly blocked without evidence artifacts."""
        # Find Phase 5d PR Creation section
        pr_section_start = self.content.find("### 5d. PR Creation")
        self.assertGreater(pr_section_start, -1)
        pr_section = self.content[pr_section_start:pr_section_start + 500]
        self.assertTrue(
            "evidence" in pr_section.lower() or "build-evidence-check" in pr_section,
            "PR Creation section must reference evidence check",
        )

    def test_dev_server_auto_start_in_validation(self):
        """Phase 3d must auto-start dev server, not just suggest it."""
        phase3d_start = self.content.find("### 3d. Human Validation")
        self.assertGreater(phase3d_start, -1)
        phase3d = self.content[phase3d_start:phase3d_start + 800]
        self.assertTrue(
            "auto-start" in phase3d.lower() or "automatically" in phase3d.lower(),
            "Phase 3d must auto-start dev server",
        )


class TestMakefile(unittest.TestCase):
    """Validate Makefile targets and policies."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, "Makefile")) as f:
            cls.content = f.read()

    def test_cursor_and_plugin_first_policy(self):
        self.assertIn("link-cursor", self.content)
        self.assertIn("rpw-building plugin", self.content)
        self.assertIn("unlink-claude-build", self.content)

    def test_unified_command_selection(self):
        self.assertIn("CURSOR_SOURCE_COMMANDS := $(wildcard $(COMMANDS_SRC)/*.md)", self.content)
        self.assertNotIn(".claude.md", self.content)

    def test_public_release_gate(self):
        self.assertIn("public-release-gate:", self.content)
        self.assertIn("PUBLIC_REPO_RELEASE_CONFIRM", self.content)
        self.assertIn("$(MAKE) public-release-gate", self.content)

    def test_required_stack_target(self):
        self.assertIn("required-stack:", self.content)
        self.assertIn("scripts/enable_required_stack.py", self.content)

    def test_verify_uses_build_state(self):
        self.assertIn("_build_state_file", self.content)
        self.assertIn("build_state_set verify_passed", self.content)


class TestAutoDispatchSkill(unittest.TestCase):
    """Validate auto-dispatch skill structure and cross-references."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, "plugins", "rpw-building", "skills", "auto-dispatch", "SKILL.md")) as f:
            cls.content = f.read()

    def test_has_all_dispatch_categories(self):
        for section in ["Minion Tasks", "Research Tasks", "Debugging Tasks", "Guardrails"]:
            self.assertIn(section, self.content, f"auto-dispatch must have: {section}")

    def test_documents_parallel_fan_out(self):
        self.assertIn("rw-", self.content, "must use rw- naming for Research Workers")
        self.assertIn("research-", self.content, "must use research- naming for Research Agents")
        self.assertIn("cannot spawn subagents", self.content, "must document depth=1 limitation")

    def test_references_shared_guardrails(self):
        self.assertIn("subagent-dispatch", self.content)
        self.assertIn("bypassPermissions", self.content)

    def test_excludes_build_sessions(self):
        self.assertIn("/build", self.content)
        self.assertIn("does NOT apply during", self.content)


class TestSubagentDispatchSkill(unittest.TestCase):
    """Validate subagent-dispatch skill structure."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, "plugins", "rpw-building", "skills", "subagent-dispatch", "SKILL.md")) as f:
            cls.content = f.read()

    def test_has_bypass_security_denylist(self):
        self.assertIn("bypassPermissions", self.content)
        self.assertIn(".env", self.content)
        self.assertIn("~/.aws", self.content)

    def test_has_failure_handling(self):
        self.assertIn("Failure Handling", self.content)


class TestAgentsMd(unittest.TestCase):
    """Validate AGENTS.md references and structure."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, "plugins", "rpw-building", "AGENTS.md")) as f:
            cls.content = f.read()

    def test_references_auto_dispatch(self):
        self.assertIn("auto-dispatch", self.content)

    def test_has_bead_hierarchy(self):
        self.assertIn("Bead Level", self.content)
        self.assertIn("Bead Hierarchy", self.content)


class TestDatabricksAppsSkill(unittest.TestCase):
    """Validate the databricks-apps skill has required content."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        cls.skill_path = os.path.join(root, "plugins", "rpw-building", "skills", "databricks-apps", "SKILL.md")
        with open(cls.skill_path) as f:
            cls.content = f.read()

    def test_skill_exists(self):
        self.assertTrue(os.path.isfile(self.skill_path), "databricks-apps SKILL.md must exist")

    def test_skill_references_template_url(self):
        self.assertIn(
            "github.com/randypitcherii/shareables",
            self.content,
            "Skill must reference the shareables GitHub repo",
        )

    def test_skill_has_copy_command(self):
        """Skill must instruct the agent to copy the exact template, not scaffold from scratch."""
        self.assertIn("sparse-checkout", self.content, "Skill must include sparse-checkout clone command")
        self.assertIn("cp -r", self.content, "Skill must include copy command for template files")
        self.assertIn("Do NOT scaffold from scratch", self.content, "Skill must prohibit scaffolding from scratch")

    def test_skill_documents_bash_over_rest_pattern(self):
        self.assertIn("Bash-over-REST", self.content, "Skill must document the bash-over-REST pattern")
        self.assertIn("/api/v1/shell/run", self.content, "Skill must document the shell/run endpoint")

    def test_skill_documents_local_dev_workflow(self):
        self.assertIn("make dev", self.content, "Skill must document 'make dev' for local iteration")
        self.assertIn("--reload", self.content, "Skill must document uvicorn --reload for hot-reload")

    def test_skill_documents_lakebase_connectivity(self):
        self.assertIn("PGHOST", self.content, "Skill must document auto-injected PGHOST")
        self.assertIn("M2M OAuth", self.content, "Skill must document M2M OAuth recipe")
        self.assertIn("CREATE SCHEMA", self.content, "Skill must warn about public schema restriction")

    def test_skill_documents_app_yaml(self):
        self.assertIn("app.yaml", self.content, "Skill must document app.yaml configuration")
        self.assertIn("uv sync --frozen", self.content, "Skill must document frozen uv sync in production")

    def test_skill_documents_dab_deployment(self):
        self.assertIn("databricks.yml", self.content, "Skill must document DAB config")
        self.assertIn("deploy-dev", self.content, "Skill must document dev deployment target")
        self.assertIn("deploy-prod", self.content, "Skill must document prod deployment target")


class TestHookRecovery(unittest.TestCase):
    """Validate hook changes for the silent-stop bug fix."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, ".claude", "hooks", "file-protection.sh")) as f:
            cls.file_protection = f.read()
        with open(os.path.join(root, ".claude", "hooks", "build-compliance.sh")) as f:
            cls.build_compliance = f.read()

    def test_file_protection_still_warns_on_manifests(self):
        """file-protection.sh must still warn on marketplace.json and plugin.json edits."""
        self.assertIn("marketplace.json", self.file_protection, "Must still warn on marketplace.json edits")
        self.assertIn("plugin.json", self.file_protection, "Must still warn on plugin.json edits")

    def test_build_compliance_uses_build_state(self):
        """build-compliance.sh must use build-state.sh for checkpoint verification."""
        self.assertIn("build-state.sh", self.build_compliance, "Must source build-state.sh")
        self.assertIn("build_state_get", self.build_compliance, "Must use build_state_get for checkpoint checks")
        self.assertNotIn("active-build", self.build_compliance, "Must not use old active-build flat file")

    def test_build_compliance_has_recovery_message(self):
        """Hook block messages must include recovery instruction."""
        self.assertIn("BLOCKED:", self.build_compliance, "Block messages must include BLOCKED prefix")
        self.assertIn("make verify", self.build_compliance, "Recovery must tell agent to run 'make verify'")

    def test_file_protection_does_not_block_env(self):
        """.env protection moved to CLAUDE.md — hook must not hard-block .env files."""
        self.assertNotIn(
            "*.env|*.env.*",
            self.file_protection,
            "file-protection.sh must not hard-block .env files (moved to CLAUDE.md policy)",
        )

    def test_claude_md_has_env_policy(self):
        """CLAUDE.md must contain .env protection policy."""
        root = _repo_root()
        with open(os.path.join(root, "CLAUDE.md")) as f:
            content = f.read()
        self.assertIn(
            ".env",
            content,
            "CLAUDE.md must mention .env file handling policy",
        )
        self.assertTrue(
            "never commit" in content.lower() or "secrets" in content.lower(),
            "CLAUDE.md must warn about .env files containing secrets",
        )

class TestBuildCompletionGate(unittest.TestCase):
    """Validate build-completion-gate.sh (Stop hook) for evidence-based enforcement."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, ".claude", "hooks", "build-completion-gate.sh")) as f:
            cls.gate_content = f.read()

    def test_gate_checks_all_five_evidence_phases(self):
        """Completion gate must check for all five evidence artifact phases."""
        for phase in ["verify", "security-review", "simplification", "docs-review", "retro"]:
            self.assertIn(phase, self.gate_content, f"Gate must check for {phase} evidence artifact")

    def test_gate_checks_verify_passed_checkpoint(self):
        """Completion gate must also check verify_passed state checkpoint."""
        self.assertIn("verify_passed", self.gate_content, "Gate must check verify_passed checkpoint")

    def test_gate_uses_exit_2_for_blocking(self):
        """Completion gate must use exit 2 to block stop with feedback."""
        self.assertIn("exit 2", self.gate_content, "Gate must use exit 2 to block incomplete builds")

    def test_gate_fails_open_without_active_build(self):
        """Completion gate must exit 0 (allow) when no active build state exists."""
        self.assertIn("exit 0", self.gate_content, "Gate must fail-open when no active build")


class TestBuildStateHelpers(unittest.TestCase):
    """Validate build-state.sh has required helper functions."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, ".claude", "hooks", "build-state.sh")) as f:
            cls.state_content = f.read()

    def test_has_evidence_save_function(self):
        """build-state.sh must define build_evidence_save function."""
        self.assertIn("build_evidence_save()", self.state_content)

    def test_has_evidence_check_function(self):
        """build-state.sh must define build_evidence_check function."""
        self.assertIn("build_evidence_check()", self.state_content)

    def test_has_evidence_clear_function(self):
        """build-state.sh must define build_evidence_clear function."""
        self.assertIn("build_evidence_clear()", self.state_content)

    def test_state_clear_also_clears_evidence(self):
        """build_state_clear must also clean up evidence artifacts."""
        self.assertIn("build_evidence_clear", self.state_content, "state_clear must call evidence_clear")


class TestBuildGitignoreEntries(unittest.TestCase):
    """Validate gitignore protects ephemeral build state from commits."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, ".gitignore")) as f:
            cls.gitignore = f.read()

    def test_build_state_json_is_gitignored(self):
        self.assertIn("build-state.json", self.gitignore, "build-state.json must be gitignored")

    def test_build_evidence_dir_is_gitignored(self):
        self.assertIn("build-evidence/", self.gitignore, "build-evidence/ must be gitignored")

    def test_claude_worktrees_dir_is_gitignored(self):
        self.assertIn(".claude/worktrees/", self.gitignore, ".claude/worktrees/ must be gitignored")


class TestSettingsHookWiring(unittest.TestCase):
    """Validate .claude/settings.json hook bindings match documented configuration."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        with open(os.path.join(root, ".claude", "settings.json")) as f:
            cls.settings = json.load(f)

    def test_pre_tool_use_hooks_exist(self):
        """settings.json must define PreToolUse hooks."""
        self.assertIn("hooks", self.settings)
        self.assertIn("PreToolUse", self.settings["hooks"])

    def test_file_protection_hook_wired(self):
        """Edit/Write must be gated by file-protection.sh."""
        hooks = self.settings["hooks"]["PreToolUse"]
        edit_write_hooks = [h for h in hooks if h.get("matcher") == "Edit|Write"]
        self.assertEqual(len(edit_write_hooks), 1, "Must have exactly one Edit|Write hook")
        commands = [hh["command"] for hh in edit_write_hooks[0]["hooks"]]
        self.assertTrue(any("file-protection.sh" in c for c in commands))

    def test_build_compliance_hook_wired(self):
        """Bash must be gated by build-compliance.sh."""
        hooks = self.settings["hooks"]["PreToolUse"]
        bash_hooks = [h for h in hooks if h.get("matcher") == "Bash"]
        self.assertEqual(len(bash_hooks), 1, "Must have exactly one Bash hook")
        commands = [hh["command"] for hh in bash_hooks[0]["hooks"]]
        self.assertTrue(any("build-compliance.sh" in c for c in commands))

    def test_stop_hook_wired(self):
        """Stop must be gated by build-completion-gate.sh."""
        self.assertIn("Stop", self.settings["hooks"])
        stop_hooks = self.settings["hooks"]["Stop"]
        self.assertTrue(len(stop_hooks) > 0, "Must have at least one Stop hook")
        all_commands = []
        for entry in stop_hooks:
            for h in entry.get("hooks", []):
                all_commands.append(h.get("command", ""))
        self.assertTrue(any("build-completion-gate.sh" in c for c in all_commands))


class TestBeadsHierarchyStandard(unittest.TestCase):
    """Validate beads hierarchy standard documentation and cross-references."""

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        cls.root = root
        cls.hierarchy_path = os.path.join(root, "docs", "beads-hierarchy-standard.md")
        if os.path.isfile(cls.hierarchy_path):
            with open(cls.hierarchy_path) as f:
                cls.hierarchy_content = f.read()
        else:
            cls.hierarchy_content = ""

    def test_hierarchy_standard_doc_exists(self):
        """Hierarchy standard reference doc must exist."""
        self.assertTrue(
            os.path.isfile(self.hierarchy_path),
            "docs/beads-hierarchy-standard.md must exist",
        )

    def test_hierarchy_defines_three_levels(self):
        """Hierarchy doc must define epic, feature, and task levels."""
        for level in ["epic", "feature", "task"]:
            self.assertIn(
                f"--type={level}",
                self.hierarchy_content,
                f"Hierarchy doc must define --type={level}",
            )

    def test_hierarchy_defines_rules(self):
        """Hierarchy doc must define structural rules."""
        self.assertIn("parent-child", self.hierarchy_content, "Must reference parent-child dependency type")
        self.assertIn("MUST", self.hierarchy_content, "Must have mandatory rules")

    def test_hierarchy_has_command_examples(self):
        """Hierarchy doc must include bd command examples."""
        self.assertIn("bd create", self.hierarchy_content, "Must show bd create examples")
        self.assertIn("bd dep add", self.hierarchy_content, "Must show bd dep add examples")

    def test_hierarchy_defines_lifecycle(self):
        """Hierarchy doc must define lifecycle for each level."""
        self.assertIn("Lifecycle", self.hierarchy_content, "Must have lifecycle section")

    def test_cross_references_exist(self):
        """Hierarchy must be referenced in build.md, subagent-dispatch, and AGENTS.md."""
        root = self.root
        with open(os.path.join(root, "plugins", "rpw-building", "commands", "build.md")) as f:
            build_content = f.read()
        self.assertIn("beads-hierarchy-standard", build_content)
        self.assertIn("feature bead", build_content)
        self.assertIn("task bead", build_content)

        with open(os.path.join(root, "plugins", "rpw-building", "skills", "subagent-dispatch", "SKILL.md")) as f:
            dispatch_content = f.read()
        self.assertIn("Bead Level", dispatch_content)
        self.assertIn("Hierarchy", dispatch_content)


class TestSkillFileQuality(unittest.TestCase):
    """Static quality checks for SKILL.md instruction files."""

    MAX_WORDS = 1600
    MAX_DESCRIPTION_CHARS = 500

    @classmethod
    def setUpClass(cls):
        root = _repo_root()
        cls.skill_files = []
        for plugin in ["rpw-building", "rpw-working", "rpw-databricks"]:
            skills_dir = os.path.join(root, "plugins", plugin, "skills")
            if not os.path.isdir(skills_dir):
                continue
            for skill in os.listdir(skills_dir):
                path = os.path.join(skills_dir, skill, "SKILL.md")
                if os.path.isfile(path):
                    cls.skill_files.append(path)
        cls.skill_names = {os.path.basename(os.path.dirname(p)) for p in cls.skill_files}

    @staticmethod
    def _strip_code_blocks(content):
        """Remove fenced code blocks (``` or ~~~) to avoid counting code comments as headings."""
        return re.sub(r"```.*?```", "", content, flags=re.DOTALL)

    @staticmethod
    def _parse_frontmatter(content):
        """Return (frontmatter_dict, body) if content starts with YAML frontmatter, else (None, content)."""
        if not content.startswith("---"):
            return None, content
        end = content.find("\n---", 3)
        if end == -1:
            return None, content
        fm_text = content[3:end].strip()
        fm = {}
        for line in fm_text.splitlines():
            if ":" in line:
                key, _, val = line.partition(":")
                fm[key.strip()] = val.strip()
        body = content[end + 4:]
        return fm, body

    def test_skill_files_under_word_limit(self):
        """Each SKILL.md must be under MAX_WORDS words to avoid LLM attention degradation."""
        violations = []
        for path in self.skill_files:
            with open(path) as f:
                word_count = len(f.read().split())
            if word_count >= self.MAX_WORDS:
                skill = os.path.basename(os.path.dirname(path))
                violations.append(f"{skill}: {word_count} words (max {self.MAX_WORDS})")
        self.assertEqual(
            violations,
            [],
            "These SKILL.md files exceed the word limit:\n" + "\n".join(violations),
        )

    def test_skill_files_have_valid_frontmatter(self):
        """Every SKILL.md must have YAML frontmatter with non-empty name and description."""
        failures = []
        for path in self.skill_files:
            skill = os.path.basename(os.path.dirname(path))
            with open(path) as f:
                content = f.read()
            fm, _ = self._parse_frontmatter(content)
            if fm is None:
                failures.append(f"{skill}: missing YAML frontmatter (must start with ---)")
                continue
            if not fm.get("name", "").strip():
                failures.append(f"{skill}: frontmatter missing non-empty 'name' field")
            if not fm.get("description", "").strip():
                failures.append(f"{skill}: frontmatter missing non-empty 'description' field")
        self.assertEqual(
            failures,
            [],
            "Frontmatter validation failures:\n" + "\n".join(failures),
        )

    def test_skill_description_under_char_limit(self):
        """SKILL.md description field must be under MAX_DESCRIPTION_CHARS characters."""
        violations = []
        for path in self.skill_files:
            skill = os.path.basename(os.path.dirname(path))
            with open(path) as f:
                content = f.read()
            fm, _ = self._parse_frontmatter(content)
            if fm is None:
                continue  # caught by test_skill_files_have_valid_frontmatter
            desc = fm.get("description", "")
            if len(desc) >= self.MAX_DESCRIPTION_CHARS:
                violations.append(f"{skill}: description is {len(desc)} chars (max {self.MAX_DESCRIPTION_CHARS})")
        self.assertEqual(
            violations,
            [],
            "Description length violations:\n" + "\n".join(violations),
        )

    def test_cross_references_to_internal_skills_resolve(self):
        """If a SKILL.md references another skill that exists in this repo, it must still exist."""
        # Pattern: backtick-quoted name followed by "skill" — e.g. `subagent-dispatch` skill
        ref_pattern = re.compile(r"`([a-z][a-z0-9-]*)`\s+skill")
        broken = []
        for path in self.skill_files:
            skill = os.path.basename(os.path.dirname(path))
            with open(path) as f:
                content = f.read()
            for match in ref_pattern.finditer(content):
                ref_name = match.group(1)
                if ref_name == skill:
                    continue  # self-reference
                # Only validate references to skills that exist (or should exist) in this repo.
                # References to external/user-environment skills are allowed to be absent.
                # We flag only when the referenced name closely matches an existing skill name
                # by checking if it's in the known skill set.
                if ref_name in self.skill_names:
                    # It exists — no problem
                    pass
                else:
                    # Unknown reference — only flag if it looks like an internal skill
                    # (uses same kebab-case conventions and doesn't look like a command/tool)
                    # Skip if content explicitly says it's an external/user-env skill
                    if "user's environment" in content or "available in the user" in content:
                        continue
                    broken.append(f"{skill}: references `{ref_name}` skill but it does not exist in this repo")
        self.assertEqual(
            broken,
            [],
            "Broken internal skill cross-references:\n" + "\n".join(broken),
        )

    def test_skill_files_have_exactly_one_h1_heading(self):
        """Every SKILL.md must have exactly one H1 heading (# Title), outside code blocks."""
        failures = []
        for path in self.skill_files:
            skill = os.path.basename(os.path.dirname(path))
            with open(path) as f:
                content = f.read()
            stripped = self._strip_code_blocks(content)
            h1_matches = re.findall(r"^# .+", stripped, re.MULTILINE)
            if len(h1_matches) != 1:
                failures.append(
                    f"{skill}: found {len(h1_matches)} H1 headings (must be exactly 1): {h1_matches}"
                )
        self.assertEqual(
            failures,
            [],
            "H1 heading violations:\n" + "\n".join(failures),
        )

    def test_skill_h1_comes_before_other_headings(self):
        """The H1 heading must be the first heading in the file (after frontmatter)."""
        failures = []
        for path in self.skill_files:
            skill = os.path.basename(os.path.dirname(path))
            with open(path) as f:
                content = f.read()
            _, body = self._parse_frontmatter(content)
            stripped = self._strip_code_blocks(body)
            headings = re.findall(r"^(#{1,6}) .+", stripped, re.MULTILINE)
            if not headings:
                failures.append(f"{skill}: no headings found in body")
                continue
            if headings[0] != "#":
                failures.append(
                    f"{skill}: first heading is '{headings[0]}' level, expected H1 ('#')"
                )
        self.assertEqual(
            failures,
            [],
            "H1 ordering violations:\n" + "\n".join(failures),
        )


class TestPortableMcpPaths(unittest.TestCase):
    ABSOLUTE_PATH_RE = re.compile(r"/(Users|home)/[^/]+/")

    def test_no_machine_specific_absolute_paths_in_mcp_files(self):
        root = _repo_root()
        checked = 0
        for path in _mcp_json_paths(root):
            if not os.path.isfile(path):
                continue
            checked += 1
            with open(path) as f:
                content = f.read()
            rel = os.path.relpath(path, root)
            self.assertFalse(
                self.ABSOLUTE_PATH_RE.search(content),
                f"{rel} contains machine-specific absolute paths (use ${{CLAUDE_PLUGIN_ROOT}} placeholders)",
            )
        self.assertGreater(checked, 0, "No MCP json files found to validate")


class TestAgentDefinitions(unittest.TestCase):
    """Validate agent files have required frontmatter and system prompts."""

    def _find_agent_files(self):
        root = _repo_root()
        agents = []
        for plugin_dir in os.listdir(os.path.join(root, "plugins")):
            agents_dir = os.path.join(root, "plugins", plugin_dir, "agents")
            if os.path.isdir(agents_dir):
                for f in sorted(os.listdir(agents_dir)):
                    if f.endswith(".md"):
                        agents.append(os.path.join(agents_dir, f))
        return agents

    def test_agent_files_exist(self):
        agents = self._find_agent_files()
        self.assertGreater(len(agents), 0, "Expected at least one agent definition")

    def test_agent_frontmatter_has_required_fields(self):
        agents = self._find_agent_files()
        for agent_path in agents:
            with open(agent_path) as f:
                content = f.read()
            rel = os.path.relpath(agent_path, _repo_root())
            self.assertTrue(content.startswith("---"),
                f"{rel} must start with YAML frontmatter")
            parts = content.split("---", 2)
            self.assertGreaterEqual(len(parts), 3,
                f"{rel} must have closing --- for frontmatter")
            frontmatter = parts[1]
            for field in ["name:", "description:", "model:", "color:"]:
                self.assertIn(field, frontmatter,
                    f"{rel} frontmatter missing {field}")

    def test_agent_has_system_prompt(self):
        agents = self._find_agent_files()
        for agent_path in agents:
            with open(agent_path) as f:
                content = f.read()
            rel = os.path.relpath(agent_path, _repo_root())
            parts = content.split("---", 2)
            body = parts[2].strip() if len(parts) >= 3 else ""
            self.assertGreater(len(body), 50,
                f"{rel} must have a substantive system prompt (>50 chars)")

    def test_agent_description_has_examples(self):
        agents = self._find_agent_files()
        for agent_path in agents:
            with open(agent_path) as f:
                content = f.read()
            rel = os.path.relpath(agent_path, _repo_root())
            parts = content.split("---", 2)
            frontmatter = parts[1] if len(parts) >= 3 else ""
            self.assertIn("<example>", frontmatter,
                f"{rel} description should include triggering examples")


if __name__ == "__main__":
    unittest.main()
