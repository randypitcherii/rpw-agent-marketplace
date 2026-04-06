import unittest
from unittest.mock import patch

import run_mcp


class TestGleanRunMcpRequired(unittest.TestCase):
    """Server-specific tests: validate the REQUIRED list for glean."""

    def test_required_contains_expected_vars(self):
        self.assertEqual(run_mcp.REQUIRED, ["GLEAN_API_TOKEN", "GLEAN_BASE_URL"])

    def test_validate_required_env_detects_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, ["GLEAN_API_TOKEN", "GLEAN_BASE_URL"])

    def test_validate_required_env_passes_when_set(self):
        env = {"GLEAN_API_TOKEN": "test-key", "GLEAN_BASE_URL": "https://test-be.glean.com"}
        with patch.dict("os.environ", env, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, [])

    def test_no_pex_dependency(self):
        """Verify we no longer depend on a PEX file."""
        self.assertFalse(hasattr(run_mcp, "PEX_PATH"))


if __name__ == "__main__":
    unittest.main()
