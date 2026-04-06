import unittest
from unittest.mock import patch

import run_mcp


class TestJiraRunMcpRequired(unittest.TestCase):
    """Server-specific tests: validate the REQUIRED list for jira."""

    def test_required_contains_expected_vars(self):
        self.assertEqual(run_mcp.REQUIRED, ["JIRA_API_TOKEN"])

    def test_validate_required_env_detects_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, ["JIRA_API_TOKEN"])

    def test_validate_required_env_passes_when_set(self):
        env = {"JIRA_API_TOKEN": "test-key"}
        with patch.dict("os.environ", env, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, [])

    def test_pex_path_points_to_jira(self):
        self.assertIn("jira_mcp", str(run_mcp.PEX_PATH))


if __name__ == "__main__":
    unittest.main()
