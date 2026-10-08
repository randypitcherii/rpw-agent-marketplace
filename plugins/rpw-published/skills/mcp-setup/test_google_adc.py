"""Regression coverage for deterministic gcloud ADC scope validation."""

import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_adc import (
    IncompleteAdcScopesError,
    enabled_adc_consumers,
    missing_scopes,
    remediation_command,
)


class TestGoogleAdcScopeValidation(unittest.TestCase):
    def test_valid_token_missing_tasks_reports_exact_delta_and_safe_remediation(self):
        granted = set(remediation_command().split("--scopes=", 1)[1].split(","))
        granted.remove("https://www.googleapis.com/auth/tasks")

        missing = missing_scopes(granted)
        error = IncompleteAdcScopesError(missing, enabled_adc_consumers())

        self.assertEqual(missing, ("https://www.googleapis.com/auth/tasks",))
        self.assertIn("https://www.googleapis.com/auth/tasks", str(error))
        self.assertIn(remediation_command(), str(error))
        self.assertIn("replaces the existing ADC grant", str(error))

    def test_remediation_preserves_all_enabled_consumer_scopes(self):
        command = remediation_command(("google-docs", "google-tasks", "gemini-image", "core_identity"))
        scopes = set(command.split("--scopes=", 1)[1].split(","))

        self.assertIn("https://www.googleapis.com/auth/tasks", scopes)
        self.assertIn("https://www.googleapis.com/auth/documents", scopes)
        self.assertIn("https://www.googleapis.com/auth/drive", scopes)
        self.assertIn("https://www.googleapis.com/auth/spreadsheets", scopes)
        self.assertIn("https://www.googleapis.com/auth/presentations", scopes)
        self.assertIn("https://www.googleapis.com/auth/cloud-platform", scopes)
        self.assertIn("openid", scopes)
        self.assertIn("https://www.googleapis.com/auth/userinfo.email", scopes)

    def test_complete_token_has_no_missing_scopes(self):
        scopes = remediation_command().split("--scopes=", 1)[1].split(",")
        self.assertEqual(missing_scopes(scopes), ())

    @patch("google_adc.active_adc_scopes")
    def test_valid_but_incomplete_active_token_fails_validation(self, active_scopes):
        from google_adc import validate_active_adc

        active_scopes.return_value = {"openid"}
        with self.assertRaises(IncompleteAdcScopesError) as raised:
            validate_active_adc()
        self.assertIn("https://www.googleapis.com/auth/tasks", raised.exception.missing_scopes)

    @patch("google_adc.token_scopes", return_value={"openid"})
    def test_scope_check_uses_application_default_not_user_credentials(self, token_scopes):
        from google_adc import active_adc_scopes

        calls = []

        def run(*args, **kwargs):
            calls.append((args, kwargs))
            return type("Completed", (), {"stdout": "adc-token\n"})()

        self.assertEqual(active_adc_scopes(run), {"openid"})
        self.assertEqual(calls[0][0][0], ["gcloud", "auth", "application-default", "print-access-token"])
        token_scopes.assert_called_once_with("adc-token")

    def test_user_credentials_and_uc_consumers_are_not_adc_consumers(self):
        with self.assertRaisesRegex(ValueError, "Not gcloud ADC consumers"):
            enabled_adc_consumers(("google-calendar",))
        self.assertNotIn("google-calendar", enabled_adc_consumers())
