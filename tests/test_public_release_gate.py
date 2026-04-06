"""Tests for the public repository release gate."""

from __future__ import annotations


class TestPublicReleaseGate:
    def test_flag_path_leaks_blocks_dot_env(self, load_script_module, temp_json_file):
        module = load_script_module("public_release_gate")
        root, write = temp_json_file
        write(".env", "ANYTHING=1\n")
        issues = module._flag_path_leaks(root)
        assert any(".env" in issue for issue in issues)

    def test_flag_path_leaks_allows_dot_env_example(self, load_script_module, temp_json_file):
        module = load_script_module("public_release_gate")
        root, write = temp_json_file
        write(".env.example", "TOKEN=placeholder\n")
        issues = module._flag_path_leaks(root)
        assert issues == []

    def test_flag_content_leaks_detects_private_key_marker(self, load_script_module, temp_json_file):
        module = load_script_module("public_release_gate")
        root, write = temp_json_file
        marker = "-----BEGIN " + "PRIVATE KEY-----"
        write("notes.md", f"do not commit\n{marker}\n")
        issues = module._flag_content_leaks(root)
        assert any("PRIVATE KEY" in issue for issue in issues)

    def test_validate_confirmation_requires_explicit_ack(self, load_script_module):
        module = load_script_module("public_release_gate")
        import pytest

        with pytest.raises(ValueError):
            module._validate_confirmation(require_confirmation=True, confirmation_value="")

        module._validate_confirmation(
            require_confirmation=True,
            confirmation_value=module.REQUIRED_ACK_VALUE,
        )
