import unittest
from unittest.mock import patch

import run_mcp


class TestGoogleTasksRunMcpRequired(unittest.TestCase):
    """Server-specific tests: validate the REQUIRED list for google-tasks."""

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
            "GOOGLE_CLIENT_ID": "id",
            "GOOGLE_CLIENT_SECRET": "secret",
            "GOOGLE_REFRESH_TOKEN": "token",
        }
        with patch.dict("os.environ", env, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
