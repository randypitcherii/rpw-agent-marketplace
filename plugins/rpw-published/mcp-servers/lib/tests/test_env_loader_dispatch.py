"""Tests for CREDENTIAL_SOURCE dispatch in env_loader."""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.env_loader import _parse_field_map


class TestParseFieldMap(unittest.TestCase):
    def test_empty_string_returns_empty_dict(self):
        self.assertEqual(_parse_field_map(""), {})

    def test_none_returns_empty_dict(self):
        self.assertEqual(_parse_field_map(None), {})

    def test_single_pair(self):
        self.assertEqual(
            _parse_field_map("api_key:EXA_API_KEY"),
            {"api_key": "EXA_API_KEY"},
        )

    def test_multiple_pairs(self):
        self.assertEqual(
            _parse_field_map("api_token:GLEAN_API_TOKEN,base_url:GLEAN_BASE_URL"),
            {"api_token": "GLEAN_API_TOKEN", "base_url": "GLEAN_BASE_URL"},
        )

    def test_whitespace_trimmed(self):
        self.assertEqual(
            _parse_field_map("  api_key : EXA_API_KEY , foo : BAR "),
            {"api_key": "EXA_API_KEY", "foo": "BAR"},
        )

    def test_malformed_pair_raises(self):
        with self.assertRaises(ValueError):
            _parse_field_map("api_key_without_colon")


class TestLoadSelectedEnvDispatch(unittest.TestCase):
    def setUp(self):
        # Clean env between tests so leaked vars don't confuse us
        for key in list(os.environ.keys()):
            if key.startswith(("EXA_", "UC_", "DATABRICKS_", "CREDENTIAL_", "APP_ENV")):
                del os.environ[key]

    def _write_dev_env(self, tmpdir: Path, content: str) -> Path:
        env_path = tmpdir / "dev.env"
        env_path.write_text(content)
        return env_path

    def test_no_credential_source_skips_resolver(self):
        import tempfile

        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            self._write_dev_env(tmpdir, "FOO=bar\n")
            # Patch resolve_credentials to detect accidental calls
            with mock.patch("lib.env_loader.resolve_credentials") as m:
                load_selected_env(tmpdir)
                m.assert_not_called()
            self.assertEqual(os.environ.get("FOO"), "bar")

    def test_uc_connection_dispatch_invokes_resolver(self):
        import tempfile

        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            self._write_dev_env(
                tmpdir,
                "CREDENTIAL_SOURCE=uc_connection\n"
                "DATABRICKS_PROFILE=test-profile\n"
                "UC_CONNECTION_NAME=exa\n"
                "UC_FIELD_MAP=api_key:EXA_API_KEY\n",
            )
            with mock.patch("lib.env_loader.resolve_credentials") as m:
                load_selected_env(tmpdir)
                m.assert_called_once_with(
                    "uc_connection",
                    {
                        "connection_name": "exa",
                        "databricks_profile": "test-profile",
                        "env_var_map": {"api_key": "EXA_API_KEY"},
                    },
                )

    def test_gcloud_adc_dispatch_invokes_resolver(self):
        import tempfile

        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            self._write_dev_env(
                tmpdir,
                "CREDENTIAL_SOURCE=gcloud_adc\n"
                "GCLOUD_FIELD_MAP=client_id:GOOGLE_CLIENT_ID,refresh_token:GOOGLE_REFRESH_TOKEN\n",
            )
            with mock.patch("lib.env_loader.resolve_credentials") as m:
                load_selected_env(tmpdir)
                m.assert_called_once_with(
                    "gcloud_adc",
                    {
                        "env_var_map": {
                            "client_id": "GOOGLE_CLIENT_ID",
                            "refresh_token": "GOOGLE_REFRESH_TOKEN",
                        },
                    },
                )

    def test_unknown_source_raises(self):
        import tempfile

        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            self._write_dev_env(
                tmpdir,
                "CREDENTIAL_SOURCE=bogus\n",
            )
            with self.assertRaises(ValueError):
                load_selected_env(tmpdir)

    def test_uc_proxy_dispatch_invokes_resolver(self):
        import tempfile
        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            self._write_dev_env(
                tmpdir,
                "CREDENTIAL_SOURCE=uc_proxy\n"
                "DATABRICKS_PROFILE=test-profile\n"
                "UC_CONNECTION_NAME=slack\n",
            )
            with mock.patch("lib.env_loader.resolve_credentials") as m:
                load_selected_env(tmpdir)
                m.assert_called_once_with(
                    "uc_proxy",
                    {
                        "connection_name": "slack",
                        "databricks_profile": "test-profile",
                    },
                )

    def test_databricks_secrets_dispatch_invokes_resolver(self):
        import tempfile

        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            self._write_dev_env(
                tmpdir,
                "CREDENTIAL_SOURCE=databricks_secrets\n"
                "DATABRICKS_PROFILE=DEFAULT\n"
                "DATABRICKS_SECRET_SCOPE=my_project_secrets\n"
                "DATABRICKS_SECRET_MAP=gemini_api_key:GEMINI_API_KEY\n",
            )
            with mock.patch("lib.env_loader.resolve_credentials") as m:
                load_selected_env(tmpdir)
                m.assert_called_once_with(
                    "databricks_secrets",
                    {
                        "scope": "my_project_secrets",
                        "databricks_profile": "DEFAULT",
                        "secret_map": {"gemini_api_key": "GEMINI_API_KEY"},
                    },
                )


class TestSharedConfigLoaded(unittest.TestCase):
    def setUp(self):
        for key in list(os.environ.keys()):
            if key.startswith(
                ("SHARED_", "PER_SERVER_", "APP_ENV", "CREDENTIAL_")
            ):
                del os.environ[key]

    def test_shared_config_loaded_before_per_server(self):
        """Vars in ~/.claude/mcp-servers/.shared.env load first; per-server overrides."""
        import tempfile

        from lib import env_loader
        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            # Simulate shared config at a fake STABLE_CONFIG_ROOT
            fake_shared_root = tmp_root / "shared-root"
            fake_shared_root.mkdir()
            shared_path = fake_shared_root / ".shared.env"
            shared_path.write_text("SHARED_VAR=from_shared\nPER_SERVER_OVERRIDE=shared_wins\n")

            server_dir = tmp_root / "server"
            server_dir.mkdir()
            (server_dir / "dev.env").write_text("PER_SERVER_OVERRIDE=server_wins\n")

            with mock.patch.object(env_loader, "STABLE_CONFIG_ROOT", fake_shared_root), \
                 mock.patch.object(env_loader, "SHARED_CONFIG_FILE", shared_path):
                load_selected_env(server_dir)

            # Shared var is available, and per-server overrides shared
            self.assertEqual(os.environ.get("SHARED_VAR"), "from_shared")
            self.assertEqual(os.environ.get("PER_SERVER_OVERRIDE"), "server_wins")

    def test_no_shared_config_is_fine(self):
        """Missing .shared.env shouldn't fail load_selected_env."""
        import tempfile

        from lib import env_loader
        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            server_dir = tmp_root / "server"
            server_dir.mkdir()
            (server_dir / "dev.env").write_text("FOO=bar\n")

            # Point shared config at a file that doesn't exist
            nonexistent_shared = tmp_root / "nonexistent" / ".shared.env"
            with mock.patch.object(env_loader, "SHARED_CONFIG_FILE", nonexistent_shared):
                load_selected_env(server_dir)  # Should not raise

            self.assertEqual(os.environ.get("FOO"), "bar")


class TestGcloudAdcEmptyMap(unittest.TestCase):
    def test_empty_map_skips_adc_file_check(self):
        """An empty field map should be a no-op — don't require the ADC file."""
        from lib.resolvers.gcloud_adc import resolve

        # Point at a path that definitely doesn't exist. With empty map, should not raise.
        fake_path = Path("/nonexistent/does/not/exist/adc.json")
        resolve(env_var_map={}, adc_path=fake_path)  # Should not raise


class TestStableConfigFallback(unittest.TestCase):
    def setUp(self):
        for key in list(os.environ.keys()):
            if key.startswith(
                ("FOO_", "APP_ENV", "CREDENTIAL_", "UC_", "DATABRICKS_", "GCLOUD_")
            ):
                del os.environ[key]

    def test_stable_path_used_when_local_missing(self):
        """When base_dir has no dev.env, fall back to ~/.claude/mcp-servers/<name>/dev.env."""
        import tempfile

        from lib import env_loader
        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            # Server dir is empty (no dev.env)
            server_dir = tmp_root / "empty-server"
            server_dir.mkdir()
            # Stable path has the env file
            stable_root = tmp_root / "stable"
            stable_dir = stable_root / "empty-server"
            stable_dir.mkdir(parents=True)
            (stable_dir / "dev.env").write_text("FOO_FROM_STABLE=1\n")

            with mock.patch.object(env_loader, "STABLE_CONFIG_ROOT", stable_root):
                app_env, env_path = load_selected_env(server_dir)

            self.assertEqual(env_path, stable_dir / "dev.env")
            self.assertEqual(os.environ.get("FOO_FROM_STABLE"), "1")

    def test_local_path_preferred_over_stable(self):
        """If base_dir has dev.env, use it — stable path is only a fallback."""
        import tempfile

        from lib import env_loader
        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            server_dir = tmp_root / "my-server"
            server_dir.mkdir()
            (server_dir / "dev.env").write_text("FOO_FROM_LOCAL=1\n")

            stable_root = tmp_root / "stable"
            stable_dir = stable_root / "my-server"
            stable_dir.mkdir(parents=True)
            (stable_dir / "dev.env").write_text("FOO_FROM_STABLE=1\n")

            with mock.patch.object(env_loader, "STABLE_CONFIG_ROOT", stable_root):
                _, env_path = load_selected_env(server_dir)

            self.assertEqual(env_path, server_dir / "dev.env")
            self.assertEqual(os.environ.get("FOO_FROM_LOCAL"), "1")
            # Stable file should NOT have been loaded
            self.assertIsNone(os.environ.get("FOO_FROM_STABLE"))

    def test_missing_both_raises_with_helpful_message(self):
        import tempfile

        from lib import env_loader
        from lib.env_loader import load_selected_env

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            server_dir = tmp_root / "nothing-configured"
            server_dir.mkdir()
            stable_root = tmp_root / "stable"  # empty

            with mock.patch.object(env_loader, "STABLE_CONFIG_ROOT", stable_root):
                with self.assertRaises(FileNotFoundError) as ctx:
                    load_selected_env(server_dir)

            msg = str(ctx.exception)
            self.assertIn("/mcp-setup", msg)
            self.assertIn("nothing-configured", msg)


if __name__ == "__main__":
    unittest.main()
