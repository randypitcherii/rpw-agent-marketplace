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


if __name__ == "__main__":
    unittest.main()
