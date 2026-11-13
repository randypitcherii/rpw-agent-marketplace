import unittest
from unittest.mock import patch

import run_mcp


class TestCredentialValidation(unittest.TestCase):
    """Startup validation for Vertex AI auth (project + gcloud ADC)."""

    def test_missing_project(self):
        with patch.dict("os.environ", {}, clear=True):
            msg = run_mcp._credential_error("dev.env", "dev")
            self.assertIsNotNone(msg)
            self.assertIn("GOOGLE_CLOUD_PROJECT", msg)

    def test_missing_adc(self):
        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "p"}, clear=True):
            with patch.object(run_mcp, "_adc_available", return_value=False):
                msg = run_mcp._credential_error("dev.env", "dev")
                self.assertIsNotNone(msg)
                self.assertIn("application-default login", msg)

    def test_ok_with_project_and_adc(self):
        with patch.dict("os.environ", {"GOOGLE_CLOUD_PROJECT": "p"}, clear=True):
            with patch.object(run_mcp, "_adc_available", return_value=True):
                self.assertIsNone(run_mcp._credential_error("dev.env", "dev"))


class TestDatabricksBackendValidation(unittest.TestCase):
    """GEMINI_IMAGE_BACKEND=databricks needs no Google project or ADC (#2563)."""

    def test_databricks_backend_skips_google_checks(self):
        env = {"GEMINI_IMAGE_BACKEND": "databricks", "GEMINI_IMAGE_DATABRICKS_PROFILE": "my-profile"}
        with patch.dict("os.environ", env, clear=True):
            with patch.object(run_mcp, "_databricks_profile_exists", return_value=True):
                self.assertIsNone(run_mcp._credential_error("dev.env", "dev"))

    def test_databricks_backend_missing_profile(self):
        env = {"GEMINI_IMAGE_BACKEND": "databricks", "GEMINI_IMAGE_DATABRICKS_PROFILE": "nope"}
        with patch.dict("os.environ", env, clear=True):
            with patch.object(run_mcp, "_databricks_profile_exists", return_value=False):
                msg = run_mcp._credential_error("dev.env", "dev")
                self.assertIn("nope", msg)
                self.assertIn("databricks auth login --profile nope", msg)

    def test_unknown_backend(self):
        with patch.dict("os.environ", {"GEMINI_IMAGE_BACKEND": "openai"}, clear=True):
            msg = run_mcp._credential_error("dev.env", "dev")
            self.assertIn("GEMINI_IMAGE_BACKEND", msg)


class TestProcessEnvPinsBeatEnvFile(unittest.TestCase):
    """#2611: a launcher-supplied backend/profile must survive dev.env's override=True."""

    def _run_selfcheck(self, dev_env: str, process_env: dict) -> dict:
        import os
        import tempfile
        from pathlib import Path

        from lib import env_loader, launcher

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "gemini-image"
            base.mkdir()
            (base / "dev.env").write_text(dev_env)
            with patch.dict("os.environ", {"APP_ENV": "dev", **process_env}, clear=True):
                pins = run_mcp.explicit_pins()
                # Hermetic: the host's shared user-level env file must not leak in.
                with patch.object(env_loader, "SHARED_CONFIG_FILE", base / "absent.env"), \
                        patch.object(run_mcp, "_databricks_profile_exists", return_value=True), \
                        patch.object(launcher.telemetry, "install", return_value=False):
                    with self.assertRaises(SystemExit) as exit_:
                        launcher.run(base, precheck=run_mcp.pinned_precheck(pins), selfcheck=True)
                self.assertEqual(exit_.exception.code, 0)
                return {k: os.environ.get(k) for k in run_mcp.PINNABLE_KEYS}

    def test_explicit_backend_and_profile_win_over_env_file(self):
        seen = self._run_selfcheck(
            "GEMINI_IMAGE_BACKEND=vertex\nGEMINI_IMAGE_DATABRICKS_PROFILE=file-profile\nGOOGLE_CLOUD_PROJECT=p\n",
            {"GEMINI_IMAGE_BACKEND": "databricks", "GEMINI_IMAGE_DATABRICKS_PROFILE": "pinned-profile"},
        )
        self.assertEqual(seen, {"GEMINI_IMAGE_BACKEND": "databricks",
                                "GEMINI_IMAGE_DATABRICKS_PROFILE": "pinned-profile"})

    def test_env_file_still_wins_when_nothing_is_pinned(self):
        seen = self._run_selfcheck(
            "GEMINI_IMAGE_BACKEND=databricks\nGEMINI_IMAGE_DATABRICKS_PROFILE=file-profile\n", {}
        )
        self.assertEqual(seen, {"GEMINI_IMAGE_BACKEND": "databricks",
                                "GEMINI_IMAGE_DATABRICKS_PROFILE": "file-profile"})

    def test_only_pinnable_keys_are_pinned(self):
        pins = run_mcp.explicit_pins({"GEMINI_IMAGE_BACKEND": "databricks", "GOOGLE_CLOUD_PROJECT": "x",
                                      "GEMINI_IMAGE_DATABRICKS_PROFILE": "  "})
        self.assertEqual(pins, {"GEMINI_IMAGE_BACKEND": "databricks"})


if __name__ == "__main__":
    unittest.main()
