"""Tests for provider-agnostic stale-auth detection + short-circuit (issue #195).

Covers the three responsibilities of ``lib.stale_auth``:
  1. Detection — classify Gemini/Google/Databricks expiry signatures, reject noise.
  2. Normalization — the consistent, actionable JSON error envelope shape.
  3. Short-circuit — the in-process latch stops re-hitting the provider until reset.
"""

import json
import sys
import unittest
from pathlib import Path

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.errors import CredentialResolutionError
from lib.stale_auth import (
    STALE_AUTH_KIND,
    StaleAuthError,
    StaleAuthGuard,
    looks_like_stale_auth,
)


class TestDetection(unittest.TestCase):
    """looks_like_stale_auth classifies the common provider signatures."""

    def test_gemini_api_key_expired(self):
        # The exact issue #195 motivating string.
        msg = (
            "400 INVALID_ARGUMENT. API key expired. Please renew the API key."
        )
        self.assertTrue(looks_like_stale_auth(msg))

    def test_gemini_api_key_invalid(self):
        self.assertTrue(looks_like_stale_auth("API_KEY_INVALID: API key not valid"))

    def test_google_unauthenticated_401(self):
        self.assertTrue(
            looks_like_stale_auth(
                "401 UNAUTHENTICATED: Request had invalid authentication credentials."
            )
        )

    def test_oauth_expired_token(self):
        self.assertTrue(looks_like_stale_auth("The access token has expired"))
        self.assertTrue(
            looks_like_stale_auth("invalid_grant: Token has been expired or revoked")
        )

    def test_databricks_token_expiry_reused_from_errors(self):
        # Reuses lib.errors.looks_like_databricks_auth_expired markers.
        self.assertTrue(looks_like_stale_auth("Refresh token is invalid"))
        self.assertTrue(looks_like_stale_auth("oidc: invalid_grant"))

    def test_case_insensitive(self):
        self.assertTrue(looks_like_stale_auth("API KEY EXPIRED"))

    def test_negatives_are_not_stale_auth(self):
        # Transient / unrelated failures must NOT be misclassified as stale auth.
        for benign in (
            "",
            "429 RESOURCE_EXHAUSTED: quota exceeded",
            "500 INTERNAL: backend error",
            "Connection reset by peer",
            "The model refused the prompt for safety reasons",
            "PermissionDenied: caller does not have permission",
        ):
            self.assertFalse(looks_like_stale_auth(benign), msg=benign)


class TestStaleAuthErrorEnvelope(unittest.TestCase):
    """The normalized JSON envelope is consistent and actionable."""

    def _err(self, **kw):
        defaults = dict(
            provider="vertex-ai",
            remediation="gcloud auth application-default login",
            detail="401 UNAUTHENTICATED",
        )
        defaults.update(kw)
        return StaleAuthError(**defaults)

    def test_is_credential_resolution_error(self):
        # Subclassing keeps it uniform with the rest of the auth machinery.
        self.assertIsInstance(self._err(), CredentialResolutionError)
        self.assertEqual(self._err().kind, STALE_AUTH_KIND)

    def test_as_dict_shape(self):
        env = self._err().as_dict()
        self.assertEqual(env["error"], "stale_auth")
        self.assertEqual(env["provider"], "vertex-ai")
        self.assertEqual(env["next_action"], "gcloud auth application-default login")
        self.assertFalse(env["short_circuited"])
        self.assertIn("detail", env)
        self.assertTrue(env["message"])

    def test_default_message_names_provider(self):
        self.assertIn("vertex-ai", self._err().message)

    def test_custom_message_preserved(self):
        env = self._err(message="Vertex AI rejected the credential").as_dict()
        self.assertEqual(env["message"], "Vertex AI rejected the credential")

    def test_as_message_is_parseable_json(self):
        parsed = json.loads(self._err().as_message())
        self.assertEqual(parsed["error"], "stale_auth")
        self.assertEqual(parsed["next_action"], "gcloud auth application-default login")


class TestStaleAuthGuard(unittest.TestCase):
    """The in-process latch classifies, short-circuits, and resets."""

    def setUp(self):
        self.guard = StaleAuthGuard(
            provider="vertex-ai",
            remediation="gcloud auth application-default login",
        )

    def test_starts_clean(self):
        self.assertFalse(self.guard.is_stale)
        self.assertIsNone(self.guard.short_circuit())
        self.assertIsNone(self.guard.age_seconds)

    def test_classify_non_auth_error_does_not_latch(self):
        self.assertIsNone(self.guard.classify("429 RESOURCE_EXHAUSTED"))
        self.assertFalse(self.guard.is_stale)

    def test_classify_stale_auth_latches_and_returns_envelope(self):
        err = self.guard.classify(RuntimeError("API key expired. Please renew the API key."))
        self.assertIsInstance(err, StaleAuthError)
        self.assertFalse(err.short_circuited)  # first detection is not a short-circuit
        self.assertTrue(self.guard.is_stale)
        self.assertIsNotNone(self.guard.age_seconds)

    def test_short_circuit_after_latch_marks_short_circuited(self):
        self.guard.classify("401 UNAUTHENTICATED")
        sc = self.guard.short_circuit()
        self.assertIsInstance(sc, StaleAuthError)
        self.assertTrue(sc.short_circuited)
        self.assertTrue(sc.as_dict()["short_circuited"])
        # Same remediation surfaces on the short-circuited view.
        self.assertEqual(sc.remediation, "gcloud auth application-default login")

    def test_reset_clears_latch(self):
        self.guard.classify("token has expired")
        self.assertTrue(self.guard.is_stale)
        self.guard.reset()
        self.assertFalse(self.guard.is_stale)
        self.assertIsNone(self.guard.short_circuit())


if __name__ == "__main__":
    unittest.main()
