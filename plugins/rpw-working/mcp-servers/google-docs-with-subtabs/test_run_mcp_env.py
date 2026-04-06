import unittest
from unittest.mock import patch

import run_mcp


class TestGoogleDocsRunMcpRequired(unittest.TestCase):
    """Server-specific tests: validate the REQUIRED list for google-docs."""

    def test_required_contains_gdocs_quota_project(self):
        self.assertIn("GDOCS_QUOTA_PROJECT", run_mcp.REQUIRED)

    def test_validate_required_env_detects_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, ["GDOCS_QUOTA_PROJECT"])

    def test_validate_required_env_passes_when_set(self):
        with patch.dict("os.environ", {"GDOCS_QUOTA_PROJECT": "my-project"}, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
