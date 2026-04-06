"""
Integration tests for gemini-image MCP server.

Requires GEMINI_API_KEY in environment (load via dev.env).
Run: APP_ENV=dev uv run python -m pytest test_integration.py -v

These tests hit the real Gemini API — they are slow and cost quota.
Rate-limited calls are retried with exponential backoff; persistent 429s
cause the test to be skipped (not failed).
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# Allow imports from parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load env before importing mcp_server (which reads OUTPUT_DIR at import time)
from lib.env_loader import load_selected_env

try:
    load_selected_env(Path(__file__).parent)
except FileNotFoundError:
    pass  # Skip env load if no env file — tests will skip via decorator


def _has_api_key():
    return bool(os.getenv("GEMINI_API_KEY"))


# ---------------------------------------------------------------------------
# Retry helper for rate-limited API calls
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3
_INITIAL_BACKOFF_SECS = 10


def _call_with_retry(fn, *args, **kwargs):
    """Call *fn* and retry on 429 RESOURCE_EXHAUSTED with exponential backoff.

    Returns the function result on success.
    Raises ``unittest.SkipTest`` if all retries are exhausted due to rate limits.
    Any non-rate-limit error is re-raised immediately.
    """
    last_result = None
    for attempt in range(_MAX_RETRIES + 1):
        result = fn(*args, **kwargs)
        # The MCP server functions return error strings instead of raising
        if isinstance(result, str) and "429" in result and "RESOURCE_EXHAUSTED" in result:
            last_result = result
            if attempt < _MAX_RETRIES:
                wait = _INITIAL_BACKOFF_SECS * (2 ** attempt)
                time.sleep(wait)
                continue
            raise unittest.SkipTest(
                f"Gemini API rate limit exceeded after {_MAX_RETRIES} retries"
            )
        return result
    return last_result  # pragma: no cover


# Small inter-test delay to reduce rate limit pressure
_INTER_TEST_DELAY_SECS = 2


@unittest.skipUnless(_has_api_key(), "GEMINI_API_KEY not set — skipping integration tests")
class TestGenerateImage(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="gemini_test_")
        self._patch = patch.dict(os.environ, {"GEMINI_IMAGE_OUTPUT_DIR": self.output_dir})
        self._patch.start()
        # Reimport to pick up patched OUTPUT_DIR
        import mcp_server
        mcp_server.OUTPUT_DIR = self.output_dir
        self.mcp_server = mcp_server

    def tearDown(self):
        self._patch.stop()
        # Clean up generated files
        for f in Path(self.output_dir).iterdir():
            f.unlink()
        Path(self.output_dir).rmdir()
        time.sleep(_INTER_TEST_DELAY_SECS)

    def test_generate_image_returns_valid_file(self):
        """generate_image should return a path to an actual PNG file."""
        result = _call_with_retry(
            self.mcp_server.generate_image,
            prompt="A simple red circle on a white background",
            filename="test_circle.png",
        )
        self.assertIn("Image saved to:", result)
        path = result.replace("Image saved to: ", "")
        self.assertTrue(Path(path).exists(), f"Image file should exist at {path}")
        self.assertGreater(Path(path).stat().st_size, 0, "Image file should not be empty")
        # Verify it starts with a known image header (PNG or JPEG)
        with open(path, "rb") as f:
            header = f.read(8)
        is_png = header[:4] == b"\x89PNG"
        is_jpeg = header[:2] == b"\xff\xd8"
        self.assertTrue(is_png or is_jpeg, f"File should be PNG or JPEG, got header: {header[:4]!r}")

    def test_generate_image_respects_filename(self):
        """Output file should use the provided filename."""
        result = _call_with_retry(
            self.mcp_server.generate_image,
            prompt="A blue square",
            filename="custom_name.png",
        )
        self.assertIn("custom_name.png", result)

    def test_generate_image_path_traversal_sanitized(self):
        """Filenames with path components should be stripped to basename only.

        This tests _save_image directly — no API call needed.
        """
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        path = self.mcp_server._save_image(fake_png, "../../etc/malicious.png")
        # Should be saved in output_dir, not traversed
        self.assertTrue(path.startswith(self.output_dir))
        self.assertIn("malicious.png", path)
        self.assertNotIn("etc", path)
        self.assertTrue(Path(path).exists())


@unittest.skipUnless(_has_api_key(), "GEMINI_API_KEY not set — skipping integration tests")
class TestEditImage(unittest.TestCase):
    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="gemini_test_")
        self._patch = patch.dict(os.environ, {"GEMINI_IMAGE_OUTPUT_DIR": self.output_dir})
        self._patch.start()
        import mcp_server
        mcp_server.OUTPUT_DIR = self.output_dir
        self.mcp_server = mcp_server

    def tearDown(self):
        self._patch.stop()
        for f in Path(self.output_dir).iterdir():
            f.unlink()
        Path(self.output_dir).rmdir()
        time.sleep(_INTER_TEST_DELAY_SECS)

    def test_edit_image_missing_source_returns_error(self):
        """edit_image with nonexistent source should return error without API call."""
        result = self.mcp_server.edit_image(
            image_path="/nonexistent/image.png",
            instruction="make it blue",
        )
        self.assertIn("Error: Source image not found", result)

    def test_edit_image_with_generated_source(self):
        """Generate an image, then edit it — full round trip."""
        # Step 1: Generate source image
        gen_result = _call_with_retry(
            self.mcp_server.generate_image,
            prompt="A simple red circle on a white background",
            filename="source_for_edit.png",
        )
        self.assertIn("Image saved to:", gen_result)
        source_path = gen_result.replace("Image saved to: ", "")

        # Step 2: Edit the generated image
        edit_result = _call_with_retry(
            self.mcp_server.edit_image,
            image_path=source_path,
            instruction="Change the red circle to blue",
            filename="edited_circle.png",
        )
        self.assertIn("Edited image saved to:", edit_result)
        edited_path = edit_result.replace("Edited image saved to: ", "")
        self.assertTrue(Path(edited_path).exists())
        self.assertGreater(Path(edited_path).stat().st_size, 0, "Edited image should not be empty")


@unittest.skipUnless(_has_api_key(), "GEMINI_API_KEY not set — skipping integration tests")
class TestClientSetup(unittest.TestCase):
    def test_client_connects_with_valid_key(self):
        """Verify the API key is accepted by creating a client."""
        import mcp_server
        client = mcp_server._get_client()
        self.assertIsNotNone(client)

    def test_client_fails_without_key(self):
        """Verify client raises when GEMINI_API_KEY is missing."""
        import mcp_server
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                mcp_server._get_client()


if __name__ == "__main__":
    unittest.main()
