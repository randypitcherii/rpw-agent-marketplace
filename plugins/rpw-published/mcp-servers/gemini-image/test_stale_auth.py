"""Stale-auth regression tests for the gemini-image MCP server (issue #195).

Fully mocked — no credentials or network. Verifies that a Vertex AI
stale/expired-credential failure (e.g. an expired gcloud ADC session surfacing as
`401 UNAUTHENTICATED`, or the issue's `API key expired`) is:
  1. detected and normalized into the shared actionable JSON envelope, and
  2. short-circuited on the next call so the server stops re-hitting Vertex AI.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Allow imports from parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mcp_server


class TestGeminiStaleAuth(unittest.TestCase):
    def setUp(self):
        # The guard is a process-local singleton; start each test clean.
        mcp_server._STALE_AUTH.reset()

    def tearDown(self):
        mcp_server._STALE_AUTH.reset()

    def _stale_client(self):
        """Patch _get_client so building the client raises a stale-auth error."""
        return patch.object(
            mcp_server,
            "_get_client",
            side_effect=RuntimeError(
                "401 UNAUTHENTICATED: Request had invalid authentication "
                "credentials. Reauthenticate."
            ),
        )

    # -- Detection + normalized envelope ---------------------------------------

    def test_generate_image_normalizes_stale_auth(self):
        with self._stale_client():
            result = mcp_server.generate_image(prompt="a cat", filename="c.png")
        env = json.loads(result)
        self.assertEqual(env["error"], "stale_auth")
        self.assertEqual(env["provider"], "vertex-ai")
        self.assertIn("gcloud auth application-default login", env["next_action"])
        self.assertFalse(env["short_circuited"])

    def test_edit_image_normalizes_stale_auth(self):
        # Use a real source file so edit_image reaches the client build.
        import tempfile

        src = Path(tempfile.mkdtemp()) / "src.png"
        src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        with self._stale_client():
            result = mcp_server.edit_image(image_path=str(src), instruction="blue")
        env = json.loads(result)
        self.assertEqual(env["error"], "stale_auth")
        self.assertIn("gcloud auth application-default login", env["next_action"])

    def test_gemini_api_key_expired_string_classified(self):
        # The exact issue #195 motivating error.
        with patch.object(
            mcp_server,
            "_get_client",
            side_effect=RuntimeError(
                "400 INVALID_ARGUMENT. API key expired. Please renew the API key."
            ),
        ):
            result = mcp_server.generate_image(prompt="a dog", filename="d.png")
        self.assertEqual(json.loads(result)["error"], "stale_auth")

    # -- Short-circuit ----------------------------------------------------------

    def test_second_call_short_circuits_without_hitting_provider(self):
        # First call trips the latch by hitting the (failing) provider.
        with self._stale_client() as mocked:
            first = mcp_server.generate_image(prompt="a cat", filename="c.png")
            self.assertEqual(json.loads(first)["error"], "stale_auth")
            self.assertEqual(mocked.call_count, 1)

        # Second call must NOT construct a client — it short-circuits.
        with patch.object(mcp_server, "_get_client") as never_called:
            second = mcp_server.generate_image(prompt="a cat", filename="c2.png")
        never_called.assert_not_called()
        env = json.loads(second)
        self.assertEqual(env["error"], "stale_auth")
        self.assertTrue(env["short_circuited"])

    def test_reset_reallows_provider_calls(self):
        with self._stale_client():
            mcp_server.generate_image(prompt="a cat", filename="c.png")
        self.assertTrue(mcp_server._STALE_AUTH.is_stale)

        mcp_server._STALE_AUTH.reset()

        # After reset, the next call reaches the provider again (patched to succeed).
        with patch.object(mcp_server, "_get_client") as client_ctor:
            client_ctor.return_value.models.generate_content.return_value = _no_image_response()
            result = mcp_server.generate_image(prompt="a cat", filename="c.png")
        client_ctor.assert_called_once()
        # Provider returned no image -> the structured no-image error (issue #95),
        # not a stale-auth latch.
        self.assertEqual(json.loads(result)["error"], "no_image_in_response")

    def test_non_auth_error_does_not_latch(self):
        with patch.object(
            mcp_server,
            "_get_client",
            side_effect=RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"),
        ):
            result = mcp_server.generate_image(prompt="a cat", filename="c.png")
        self.assertIn("Error generating image", result)
        self.assertFalse(mcp_server._STALE_AUTH.is_stale)


def _no_image_response():
    """A realistic 'no image part' response (text-only refusal, no metadata)."""
    from unittest.mock import MagicMock

    part = MagicMock()
    part.inline_data = None
    part.text = None
    candidate = MagicMock()
    candidate.content.parts = [part]
    candidate.finish_reason = None
    candidate.finish_message = None
    candidate.safety_ratings = []
    resp = MagicMock()
    resp.prompt_feedback = None
    resp.candidates = [candidate]
    return resp


if __name__ == "__main__":
    unittest.main()
