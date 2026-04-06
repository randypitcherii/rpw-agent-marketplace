"""Tests for PreToolUse safety hooks in rpw-building plugin.

Tests both safety-tilde-guard.sh and destructive-command-guard.sh by
piping simulated PreToolUse JSON input and checking exit codes + output.
"""

import json
import os
import subprocess
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HOOKS_DIR = os.path.join(_REPO_ROOT, "plugins", "rpw-building", "hooks")
_TILDE_GUARD = os.path.join(_HOOKS_DIR, "safety-tilde-guard.sh")
_DESTRUCTIVE_GUARD = os.path.join(_HOOKS_DIR, "destructive-command-guard.sh")


def _run_hook(script_path: str, command: str) -> subprocess.CompletedProcess:
    """Run a PreToolUse hook script with simulated JSON input."""
    input_json = json.dumps({
        "tool_name": "Bash",
        "input": {"command": command}
    })
    return subprocess.run(
        ["bash", script_path],
        input=input_json, capture_output=True, text=True, timeout=10
    )


class TestSafetyTildeGuard(unittest.TestCase):
    """Tests for safety-tilde-guard.sh — blocks mkdir ~ and rm ~ patterns."""

    def test_script_exists_and_is_executable(self):
        self.assertTrue(os.path.exists(_TILDE_GUARD), f"Hook script missing: {_TILDE_GUARD}")
        self.assertTrue(os.access(_TILDE_GUARD, os.X_OK), f"Hook script not executable: {_TILDE_GUARD}")

    # --- Should BLOCK (exit 2) ---

    def test_blocks_mkdir_bare_tilde(self):
        result = _run_hook(_TILDE_GUARD, "mkdir ~")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")
        self.assertIn("BLOCKED", result.stdout)

    def test_blocks_mkdir_tilde_slash(self):
        result = _run_hook(_TILDE_GUARD, "mkdir ~/somedir")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_mkdir_p_tilde(self):
        result = _run_hook(_TILDE_GUARD, "mkdir -p ~/somedir")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_rm_bare_tilde(self):
        result = _run_hook(_TILDE_GUARD, "rm ~")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_rm_rf_tilde(self):
        result = _run_hook(_TILDE_GUARD, "rm -rf ~")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_rm_rf_tilde_slash(self):
        result = _run_hook(_TILDE_GUARD, "rm -rf ~/")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_rm_tilde_glob(self):
        result = _run_hook(_TILDE_GUARD, "rm -rf ~/*")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_chained_mkdir_tilde(self):
        result = _run_hook(_TILDE_GUARD, "echo hello && mkdir ~")
        self.assertEqual(result.returncode, 2, f"Expected block on chained command")

    # --- Should ALLOW (exit 0) ---

    def test_allows_mkdir_normal_path(self):
        result = _run_hook(_TILDE_GUARD, "mkdir /tmp/testdir")
        self.assertEqual(result.returncode, 0)

    def test_allows_mkdir_relative_path(self):
        result = _run_hook(_TILDE_GUARD, "mkdir -p src/components")
        self.assertEqual(result.returncode, 0)

    def test_allows_rm_normal_path(self):
        result = _run_hook(_TILDE_GUARD, "rm /tmp/testfile")
        self.assertEqual(result.returncode, 0)

    def test_allows_tilde_in_string(self):
        """Commands that mention ~ in a non-dangerous context should pass."""
        result = _run_hook(_TILDE_GUARD, "echo 'home is ~'")
        self.assertEqual(result.returncode, 0)

    def test_allows_empty_command(self):
        result = _run_hook(_TILDE_GUARD, "")
        self.assertEqual(result.returncode, 0)

    def test_allows_ls_tilde(self):
        """ls ~ is safe — it's read-only."""
        result = _run_hook(_TILDE_GUARD, "ls ~")
        self.assertEqual(result.returncode, 0)


class TestDestructiveCommandGuard(unittest.TestCase):
    """Tests for destructive-command-guard.sh — blocks catastrophic commands."""

    def test_script_exists_and_is_executable(self):
        self.assertTrue(os.path.exists(_DESTRUCTIVE_GUARD), f"Hook script missing: {_DESTRUCTIVE_GUARD}")
        self.assertTrue(os.access(_DESTRUCTIVE_GUARD, os.X_OK), f"Hook script not executable: {_DESTRUCTIVE_GUARD}")

    # === Filesystem destruction ===

    def test_blocks_rm_rf_root(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "rm -rf /")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")
        self.assertIn("BLOCKED", result.stdout)

    def test_blocks_rm_rf_root_glob(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "rm -rf /*")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    # === Privilege escalation ===

    def test_blocks_sudo(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "sudo rm -rf /tmp/test")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")
        self.assertIn("BLOCKED", result.stdout)

    def test_blocks_sudo_chained(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "echo test && sudo apt install foo")
        self.assertEqual(result.returncode, 2, f"Expected block on chained sudo")

    def test_blocks_su_root(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "su root")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_su_dash(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "su -")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    # === Disk tools ===

    def test_blocks_dd(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "dd if=/dev/zero of=/dev/sda")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_mkfs(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "mkfs.ext4 /dev/sda1")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_fdisk(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "fdisk /dev/sda")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_diskutil(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "diskutil eraseDisk JHFS+ Untitled disk2")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    # === Git destructive operations ===

    def test_blocks_force_push_main(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "git push --force origin main")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_force_push_production(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "git push -f origin production")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_git_reset_hard_remote(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "git reset --hard origin/main")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    # === Process/system commands ===

    def test_blocks_shutdown(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "shutdown -h now")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_reboot(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "reboot ")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_kill_pid1(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "kill -9 1")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    def test_blocks_killall(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "killall node")
        self.assertEqual(result.returncode, 2, f"Expected block, got: {result.stdout}")

    # === Should ALLOW (exit 0) ===

    def test_allows_rm_specific_file(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "rm /tmp/testfile.txt")
        self.assertEqual(result.returncode, 0)

    def test_allows_rm_rf_specific_dir(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "rm -rf /tmp/build-output")
        self.assertEqual(result.returncode, 0)

    def test_allows_git_push_normal(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "git push origin feat/my-feature")
        self.assertEqual(result.returncode, 0)

    def test_allows_git_reset_soft(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "git reset --soft HEAD~1")
        self.assertEqual(result.returncode, 0)

    def test_allows_kill_specific_pid(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "kill 12345")
        self.assertEqual(result.returncode, 0)

    def test_allows_npm_install(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "npm install express")
        self.assertEqual(result.returncode, 0)

    def test_allows_make_verify(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "make verify")
        self.assertEqual(result.returncode, 0)

    def test_allows_empty_command(self):
        result = _run_hook(_DESTRUCTIVE_GUARD, "")
        self.assertEqual(result.returncode, 0)

    def test_allows_git_checkout_branch(self):
        """git checkout -b is safe (creating a branch), not destructive."""
        result = _run_hook(_DESTRUCTIVE_GUARD, "git checkout -b my-feature")
        self.assertEqual(result.returncode, 0)


class TestPluginJsonRegistration(unittest.TestCase):
    """Verify hooks are properly registered in plugin.json."""

    @classmethod
    def setUpClass(cls):
        plugin_json_path = os.path.join(
            _REPO_ROOT, "plugins", "rpw-building", ".claude-plugin", "plugin.json"
        )
        with open(plugin_json_path) as f:
            cls.plugin = json.load(f)

    def test_pretooluse_hooks_registered(self):
        hooks = self.plugin.get("hooks", {})
        self.assertIn("PreToolUse", hooks, "PreToolUse hooks should be registered in plugin.json")

    def test_pretooluse_has_bash_matcher(self):
        pretooluse = self.plugin["hooks"]["PreToolUse"]
        matchers = [entry.get("matcher") for entry in pretooluse]
        self.assertIn("Bash", matchers, "Should have a Bash matcher for PreToolUse")

    def test_tilde_guard_registered(self):
        pretooluse = self.plugin["hooks"]["PreToolUse"]
        all_commands = []
        for entry in pretooluse:
            for hook in entry.get("hooks", []):
                all_commands.append(hook.get("command", ""))
        self.assertTrue(
            any("safety-tilde-guard.sh" in cmd for cmd in all_commands),
            "safety-tilde-guard.sh should be registered in PreToolUse hooks"
        )

    def test_destructive_guard_registered(self):
        pretooluse = self.plugin["hooks"]["PreToolUse"]
        all_commands = []
        for entry in pretooluse:
            for hook in entry.get("hooks", []):
                all_commands.append(hook.get("command", ""))
        self.assertTrue(
            any("destructive-command-guard.sh" in cmd for cmd in all_commands),
            "destructive-command-guard.sh should be registered in PreToolUse hooks"
        )

    def test_hooks_use_plugin_root_variable(self):
        """Hooks should use ${CLAUDE_PLUGIN_ROOT} for portability."""
        pretooluse = self.plugin["hooks"]["PreToolUse"]
        for entry in pretooluse:
            for hook in entry.get("hooks", []):
                cmd = hook.get("command", "")
                if "guard.sh" in cmd:
                    self.assertIn(
                        "${CLAUDE_PLUGIN_ROOT}",
                        cmd,
                        f"Hook command should use ${{CLAUDE_PLUGIN_ROOT}}: {cmd}"
                    )


if __name__ == "__main__":
    unittest.main()
