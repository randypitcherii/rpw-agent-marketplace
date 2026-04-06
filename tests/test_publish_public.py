"""Tests for the public publish export script."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestLoadConfig:
    def test_loads_valid_config(self, load_script_module, temp_json_file):
        mod = load_script_module("publish_public")
        root, write = temp_json_file
        write(
            ".public-publish.yml",
            "exclude:\n  paths:\n    - secret/\n  patterns:\n    - '**/.env'\ntarget:\n  repo: null\n  branch: main\n",
        )
        cfg = mod.load_config(root / ".public-publish.yml")
        assert cfg["exclude"]["paths"] == ["secret/"]
        assert cfg["target"]["branch"] == "main"

    def test_raises_on_missing_config(self, load_script_module):
        mod = load_script_module("publish_public")
        import pytest

        with pytest.raises(FileNotFoundError):
            mod.load_config(Path("/nonexistent/.public-publish.yml"))


class TestFilterFiles:
    def test_excludes_exact_paths(self, load_script_module):
        mod = load_script_module("publish_public")
        config = {"exclude": {"paths": ["plugins/rpw-databricks", ".beads/"], "patterns": []}}
        files = [
            "README.md",
            "plugins/rpw-databricks/plugin.json",
            "plugins/rpw-databricks/skills/foo.md",
            "plugins/rpw-building/plugin.json",
            ".beads/metadata.json",
        ]
        result = mod.filter_files(files, config)
        assert result == ["README.md", "plugins/rpw-building/plugin.json"]

    def test_excludes_glob_patterns(self, load_script_module):
        mod = load_script_module("publish_public")
        config = {"exclude": {"paths": [], "patterns": ["**/.env", "**/.DS_Store"]}}
        files = ["README.md", ".env", "plugins/foo/.env", ".DS_Store", "src/.DS_Store"]
        result = mod.filter_files(files, config)
        assert result == ["README.md"]

    def test_preserves_env_example(self, load_script_module):
        mod = load_script_module("publish_public")
        config = {"exclude": {"paths": [], "patterns": ["**/.env"]}}
        files = [".env", ".env.example", "mcp/.env.example"]
        result = mod.filter_files(files, config)
        assert result == [".env.example", "mcp/.env.example"]


class TestPatchManifest:
    def test_removes_excluded_plugins(self, load_script_module):
        mod = load_script_module("publish_public")
        manifest = {
            "name": "rpw-agent-marketplace",
            "plugins": [
                {"name": "rpw-building", "source": "./plugins/rpw-building"},
                {"name": "rpw-working", "source": "./plugins/rpw-working"},
                {"name": "rpw-databricks", "source": "./plugins/rpw-databricks"},
            ],
        }
        excluded_paths = ["plugins/rpw-databricks"]
        result = mod.patch_manifest(manifest, excluded_paths)
        names = [p["name"] for p in result["plugins"]]
        assert names == ["rpw-building", "rpw-working"]

    def test_preserves_manifest_metadata(self, load_script_module):
        mod = load_script_module("publish_public")
        manifest = {
            "name": "rpw-agent-marketplace",
            "owner": {"name": "Randy"},
            "metadata": {"version": "1.0"},
            "plugins": [
                {"name": "rpw-building", "source": "./plugins/rpw-building"},
                {"name": "rpw-databricks", "source": "./plugins/rpw-databricks"},
            ],
        }
        result = mod.patch_manifest(manifest, ["plugins/rpw-databricks"])
        assert result["name"] == "rpw-agent-marketplace"
        assert result["owner"] == {"name": "Randy"}
        assert result["metadata"] == {"version": "1.0"}


class TestSyncFiles:
    def test_copies_files_and_removes_stale(self, load_script_module, temp_json_file):
        mod = load_script_module("publish_public")
        root, write = temp_json_file
        write("src/README.md", "hello")
        write("src/plugins/building/skill.md", "skill content")
        write("dest/old-file.txt", "stale")
        write("dest/README.md", "old hello")

        src = root / "src"
        dest = root / "dest"
        files_to_sync = ["README.md", "plugins/building/skill.md"]

        added, updated, removed = mod.sync_files(src, dest, files_to_sync)
        assert "plugins/building/skill.md" in added
        assert "README.md" in updated
        assert "old-file.txt" in removed
        assert (dest / "plugins/building/skill.md").read_text() == "skill content"
        assert not (dest / "old-file.txt").exists()

    def test_skips_git_directory(self, load_script_module, temp_json_file):
        mod = load_script_module("publish_public")
        root, write = temp_json_file
        write("src/README.md", "hello")
        write("dest/.git/config", "git stuff")
        write("dest/old.txt", "stale")

        src = root / "src"
        dest = root / "dest"

        _, _, removed = mod.sync_files(src, dest, ["README.md"])
        assert "old.txt" in removed
        assert (dest / ".git/config").exists(), ".git dir must not be touched"


class TestDryRunIntegration:
    """Integration test: dry-run against the actual repo to verify no excluded content leaks."""

    def test_dry_run_excludes_databricks_plugin(self, load_script_module):
        mod = load_script_module("publish_public")
        config = mod.load_config(REPO_ROOT / ".public-publish.yml")
        files = mod.get_tracked_files(REPO_ROOT)
        filtered = mod.filter_files(files, config)
        databricks_files = [f for f in filtered if f.startswith("plugins/rpw-databricks")]
        assert databricks_files == [], f"rpw-databricks files leaked: {databricks_files}"

    def test_dry_run_excludes_beads(self, load_script_module):
        mod = load_script_module("publish_public")
        config = mod.load_config(REPO_ROOT / ".public-publish.yml")
        files = mod.get_tracked_files(REPO_ROOT)
        filtered = mod.filter_files(files, config)
        beads_files = [f for f in filtered if f.startswith(".beads/")]
        assert beads_files == [], f".beads/ files leaked: {beads_files}"

    def test_dry_run_excludes_secret_env_files(self, load_script_module):
        mod = load_script_module("publish_public")
        config = mod.load_config(REPO_ROOT / ".public-publish.yml")
        files = mod.get_tracked_files(REPO_ROOT)
        filtered = mod.filter_files(files, config)
        # template.env files are OK (they're committed templates, not secrets)
        secret_env_files = [
            f for f in filtered
            if (f.endswith(".env") and not f.endswith("template.env"))
            or "/dev.env" in f or "/test.env" in f or "/prod.env" in f
        ]
        assert secret_env_files == [], f"Secret .env files leaked: {secret_env_files}"

    def test_dry_run_preserves_env_examples(self, load_script_module):
        mod = load_script_module("publish_public")
        config = mod.load_config(REPO_ROOT / ".public-publish.yml")
        files = mod.get_tracked_files(REPO_ROOT)
        filtered = mod.filter_files(files, config)
        examples = [f for f in filtered if ".env.example" in f]
        assert len(examples) > 0, "Expected .env.example files to be preserved"

    def test_dry_run_includes_building_and_working_plugins(self, load_script_module):
        mod = load_script_module("publish_public")
        config = mod.load_config(REPO_ROOT / ".public-publish.yml")
        files = mod.get_tracked_files(REPO_ROOT)
        filtered = mod.filter_files(files, config)
        building = [f for f in filtered if f.startswith("plugins/rpw-building")]
        working = [f for f in filtered if f.startswith("plugins/rpw-working")]
        assert len(building) > 0, "rpw-building plugin files missing"
        assert len(working) > 0, "rpw-working plugin files missing"
