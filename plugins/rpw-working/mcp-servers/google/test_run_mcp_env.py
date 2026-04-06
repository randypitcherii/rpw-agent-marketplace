import unittest
from unittest.mock import patch

import run_mcp


class TestGoogleRunMcpRequired(unittest.TestCase):
    """Server-specific tests: validate the REQUIRED list for google."""

    def test_required_contains_expected_vars(self):
        self.assertEqual(
            run_mcp.REQUIRED,
            ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"],
        )

    def test_validate_required_env_detects_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(
                missing,
                ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"],
            )

    def test_validate_required_env_passes_when_set(self):
        env = {
            "GOOGLE_CLIENT_ID": "test-id",
            "GOOGLE_CLIENT_SECRET": "test-secret",
            "GOOGLE_REFRESH_TOKEN": "test-token",
        }
        with patch.dict("os.environ", env, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, [])

    def test_pex_path_points_to_google(self):
        self.assertIn("google_mcp", str(run_mcp.PEX_PATH))


if __name__ == "__main__":
    unittest.main()
