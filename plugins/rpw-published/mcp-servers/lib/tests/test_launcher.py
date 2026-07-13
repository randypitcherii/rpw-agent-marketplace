"""Tests for the shared MCP launcher (lib.launcher.run)."""

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from lib import launcher
from lib.errors import CredentialResolutionError


def _fake_server_module(recorder):
    mod = types.ModuleType("fake_server")
    mod.main = lambda: recorder.append("started")
    return mod


class TestLauncherRun(unittest.TestCase):
    def setUp(self):
        self.started = []
        self.base = Path("/tmp/some-server")

    def _install_fake_server(self, name="fake_server"):
        sys.modules[name] = _fake_server_module(self.started)
        self.addCleanup(sys.modules.pop, name, None)
        return name

    def test_happy_path_starts_server(self):
        name = self._install_fake_server()
        with patch.object(launcher, "load_selected_env", return_value=("dev", Path("/tmp/dev.env"))):
            with patch.object(launcher, "validate_required_env", return_value=[]):
                launcher.run(self.base, required=["FOO"], server_module=name)
        self.assertEqual(self.started, ["started"])

    def test_missing_required_exits_without_starting(self):
        name = self._install_fake_server()
        with patch.object(launcher, "load_selected_env", return_value=("dev", Path("/tmp/dev.env"))):
            with patch.object(launcher, "validate_required_env", return_value=["FOO"]):
                with self.assertRaises(SystemExit) as ctx:
                    launcher.run(self.base, required=["FOO"], server_module=name)
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(self.started, [])

    def test_missing_hint_string_appended(self):
        name = self._install_fake_server()
        with patch.object(launcher, "load_selected_env", return_value=("dev", Path("/tmp/dev.env"))):
            with patch.object(launcher, "validate_required_env", return_value=["FOO"]):
                with patch("sys.stderr") as err:
                    with self.assertRaises(SystemExit):
                        launcher.run(self.base, required=["FOO"], missing_hint="do the thing", server_module=name)
        printed = "".join(c.args[0] for c in err.write.call_args_list if c.args)
        self.assertIn("do the thing", printed)

    def test_missing_hint_callable_receives_app_env(self):
        name = self._install_fake_server()
        with patch.object(launcher, "load_selected_env", return_value=("test", Path("/tmp/test.env"))):
            with patch.object(launcher, "validate_required_env", return_value=["FOO"]):
                with patch("sys.stderr") as err:
                    with self.assertRaises(SystemExit):
                        launcher.run(
                            self.base,
                            required=["FOO"],
                            missing_hint=lambda app_env: f"copy template.env to {app_env}.env",
                            server_module=name,
                        )
        printed = "".join(c.args[0] for c in err.write.call_args_list if c.args)
        self.assertIn("copy template.env to test.env", printed)

    def test_load_env_error_exits(self):
        name = self._install_fake_server()
        with patch.object(launcher, "load_selected_env", side_effect=CredentialResolutionError("boom")):
            with self.assertRaises(SystemExit) as ctx:
                launcher.run(self.base, required=["FOO"], server_module=name)
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(self.started, [])

    def test_precheck_error_blocks_start(self):
        name = self._install_fake_server()
        with patch.object(launcher, "load_selected_env", return_value=("dev", Path("/tmp/dev.env"))):
            with patch.object(launcher, "validate_required_env", return_value=[]):
                with self.assertRaises(SystemExit) as ctx:
                    launcher.run(
                        self.base,
                        precheck=lambda env_name, app_env: "auth missing",
                        server_module=name,
                    )
        self.assertEqual(ctx.exception.code, 1)
        self.assertEqual(self.started, [])

    def test_precheck_pass_starts_server(self):
        name = self._install_fake_server()
        with patch.object(launcher, "load_selected_env", return_value=("dev", Path("/tmp/dev.env"))):
            with patch.object(launcher, "validate_required_env", return_value=[]):
                launcher.run(
                    self.base,
                    precheck=lambda env_name, app_env: None,
                    server_module=name,
                )
        self.assertEqual(self.started, ["started"])

    def test_precheck_runs_after_required_check(self):
        """A missing required var aborts before the precheck runs."""
        name = self._install_fake_server()
        calls = []
        with patch.object(launcher, "load_selected_env", return_value=("dev", Path("/tmp/dev.env"))):
            with patch.object(launcher, "validate_required_env", return_value=["FOO"]):
                with self.assertRaises(SystemExit):
                    launcher.run(
                        self.base,
                        required=["FOO"],
                        precheck=lambda env_name, app_env: calls.append("precheck") or None,
                        server_module=name,
                    )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
