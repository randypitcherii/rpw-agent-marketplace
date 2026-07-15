import unittest
from unittest.mock import patch

import run_mcp


class TestJiraRunMcpRequired(unittest.TestCase):
    """Server-specific tests: validate the REQUIRED list for jira (uc_proxy)."""

    def test_required_contains_expected_vars(self):
        self.assertEqual(run_mcp.REQUIRED, ["UC_PROXY_CONNECTION_NAME", "UC_PROXY_PROFILE"])

    def test_validate_required_env_detects_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, ["UC_PROXY_CONNECTION_NAME", "UC_PROXY_PROFILE"])

    def test_validate_required_env_passes_when_set(self):
        env = {
            "UC_PROXY_CONNECTION_NAME": "test-connection",
            "UC_PROXY_PROFILE": "test-profile",
        }
        with patch.dict("os.environ", env, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
