"""Tests for required plugin stack onboarding script."""

from __future__ import annotations

import json


class TestEnableRequiredStack:
    def test_apply_required_stack_sets_all_plugins_true(self, load_script_module):
        module = load_script_module("enable_required_stack")
        settings = {"enabledPlugins": {"existing-plugin": True}}
        updated = module._apply_required_stack(settings)

        assert updated["enabledPlugins"]["existing-plugin"]
        for plugin in module.REQUIRED_PLUGINS:
            assert updated["enabledPlugins"].get(plugin), f"missing required plugin {plugin}"

    def test_load_settings_handles_missing_or_empty_file(self, load_script_module, temp_json_file):
        module = load_script_module("enable_required_stack")
        root, write = temp_json_file

        missing = root / "missing.json"
        assert module._load_settings(missing) == {}

        empty = write("empty.json", "")
        assert module._load_settings(empty) == {}

    def test_write_settings_creates_parent_directory(self, load_script_module, temp_json_file):
        module = load_script_module("enable_required_stack")
        root, _write = temp_json_file

        target = root / ".claude" / "settings.local.json"
        payload = {"enabledPlugins": {"superpowers": True}}
        module._write_settings(target, payload)
        assert target.exists()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == payload
