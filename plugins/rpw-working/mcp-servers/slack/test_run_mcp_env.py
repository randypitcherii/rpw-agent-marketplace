import unittest
from unittest.mock import patch

import run_mcp


class TestSlackRunMcpRequired(unittest.TestCase):
    """Server-specific tests: validate the REQUIRED list for slack."""

    def test_required_contains_expected_vars(self):
        self.assertEqual(run_mcp.REQUIRED, ["SLACK_BOT_TOKEN"])

    def test_validate_required_env_detects_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, ["SLACK_BOT_TOKEN"])

    def test_validate_required_env_passes_when_set(self):
        env = {"SLACK_BOT_TOKEN": "test-key"}
        with patch.dict("os.environ", env, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, [])

    def test_pex_path_points_to_slack(self):
        self.assertIn("slack_mcp", str(run_mcp.PEX_PATH))


if __name__ == "__main__":
    unittest.main()
