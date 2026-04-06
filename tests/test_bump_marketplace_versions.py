"""Focused tests for marketplace version bump tooling."""

from __future__ import annotations

from pathlib import Path


class TestReleaseLogAppend:
    def test_append_release_log_inserts_entry_after_releases_header(self, load_script_module, temp_json_file):
        module = load_script_module("bump_marketplace_versions")
        root, write = temp_json_file
        release_log = write(
            "release-log.md",
            "# Release Log\n\n"
            "## Releases\n\n"
            "## 2026-03-07 - 2026.03.0701\n\n"
            "- **Type:** release\n",
        )

        module._append_release_log(
            release_log,
            "2026.03.0802",
            ["rpw-working", "rpw-building"],
            pr_field="Unavailable (no remote configured)",
            checks_field="`make verify` \u2705",
        )

        updated = release_log.read_text(encoding="utf-8")

        assert "## 2026-03-08 - 2026.03.0802" in updated
        assert "- **Scope:** `rpw-building`, `rpw-working`" in updated
        assert "- **PR:** Unavailable (no remote configured)" in updated
        assert "- **Checks:** `make verify` \u2705" in updated

        releases_index = updated.index("## Releases")
        new_entry_index = updated.index("## 2026-03-08 - 2026.03.0802")
        old_entry_index = updated.index("## 2026-03-07 - 2026.03.0701")
        assert releases_index < new_entry_index
        assert new_entry_index < old_entry_index
