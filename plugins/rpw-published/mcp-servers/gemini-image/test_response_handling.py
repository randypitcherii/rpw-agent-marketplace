"""Fully-mocked unit tests for gemini-image response handling.

Covers the structural response parsing + magic-byte validation (issue #95) and
the model-alias resolution + unknown-model error surface (issue #350). These
tests require NO credentials or network — they mock `_get_client` — so they run
in the `make check` gate. The live round-trip suite lives in test_integration.py.

Run: uv run python -m unittest discover -p 'test_response_handling.py' -v
"""

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow imports from parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff\xe0"
_VALID_FAKE_PNG = _PNG_MAGIC + b"\x00" * 100  # Valid magic + padding
_VALID_FAKE_JPEG = _JPEG_MAGIC + b"\x00" * 100


def _make_fake_response(
    inline_data_value,
    *,
    text=None,
    finish_reason=None,
    block_reason=None,
    safety_ratings=None,
    no_candidates=False,
):
    """Build a mock Gemini response.

    inline_data_value: bytes/str for the image part, or None for no image part.
    text: optional text-part content (the model's refusal/explanation).
    finish_reason / block_reason / safety_ratings: response metadata surfaced in
    the structured no-image error (issue #95).
    no_candidates: emulate a hard block that returns an empty candidate list.
    """
    response = MagicMock()

    # prompt_feedback / block_reason
    if block_reason is not None:
        response.prompt_feedback.block_reason = block_reason
        response.prompt_feedback.block_reason_message = "prompt blocked"
    else:
        response.prompt_feedback = None

    if no_candidates:
        response.candidates = []
        return response

    parts = []
    if inline_data_value is not None:
        image_part = MagicMock()
        image_part.text = None
        image_part.inline_data = MagicMock()
        image_part.inline_data.data = inline_data_value
        parts.append(image_part)
    if text is not None:
        text_part = MagicMock()
        text_part.inline_data = None
        text_part.text = text
        parts.append(text_part)
    if not parts:
        # A candidate with no usable parts at all.
        empty_part = MagicMock()
        empty_part.inline_data = None
        empty_part.text = None
        parts.append(empty_part)

    candidate = MagicMock()
    candidate.content.parts = parts
    candidate.finish_reason = finish_reason
    candidate.finish_message = None
    candidate.safety_ratings = safety_ratings if safety_ratings is not None else []
    response.candidates = [candidate]
    return response


def _blocked_rating(category="HARM_CATEGORY_DANGEROUS_CONTENT"):
    """A mock safety rating flagged as blocked."""
    rating = MagicMock()
    rating.category = category
    rating.probability = "HIGH"
    rating.blocked = True
    return rating


class _MockClientMixin:
    """Shared setup for credential-free mock tests of both tools."""

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="gemini_mock_test_")
        self._env_patch = patch.dict(os.environ, {"GEMINI_IMAGE_OUTPUT_DIR": self.output_dir})
        self._env_patch.start()
        import mcp_server
        mcp_server.OUTPUT_DIR = self.output_dir
        self.mcp_server = mcp_server

    def tearDown(self):
        self._env_patch.stop()
        for f in Path(self.output_dir).iterdir():
            try:
                f.unlink()
            except FileNotFoundError:
                pass
        Path(self.output_dir).rmdir()

    def _mock_client(self, response=None, side_effect=None):
        """Patch _get_client so generate_content returns response or raises side_effect."""
        mock_client = MagicMock()
        if side_effect is not None:
            mock_client.models.generate_content.side_effect = side_effect
        else:
            mock_client.models.generate_content.return_value = response
        return patch.object(self.mcp_server, "_get_client", return_value=mock_client)


class TestGenerateImageByteHandling(_MockClientMixin, unittest.TestCase):
    """Mock-based branch coverage for generate_image (issue #95). No credentials."""

    def test_valid_png_writes_file(self):
        response = _make_fake_response(_VALID_FAKE_PNG)
        with self._mock_client(response):
            result = self.mcp_server.generate_image(prompt="a cat", filename="g_ok.png")
        self.assertIn("Image saved to:", result, msg=f"Unexpected: {result}")
        out_path = Path(result.replace("Image saved to: ", "").strip())
        self.assertEqual(out_path.read_bytes()[:8], _PNG_MAGIC)

    def test_valid_jpeg_writes_file(self):
        """A JPEG response is a valid image and must be written (not rejected)."""
        response = _make_fake_response(_VALID_FAKE_JPEG)
        with self._mock_client(response):
            result = self.mcp_server.generate_image(prompt="a dog", filename="g_ok.jpg")
        self.assertIn("Image saved to:", result, msg=f"Unexpected: {result}")
        out_path = Path(result.replace("Image saved to: ", "").strip())
        self.assertEqual(out_path.read_bytes()[:3], _JPEG_MAGIC[:3])

    def test_base64_string_data_decoded(self):
        b64 = base64.b64encode(_VALID_FAKE_PNG).decode("ascii")
        response = _make_fake_response(b64)
        with self._mock_client(response):
            result = self.mcp_server.generate_image(prompt="x", filename="g_b64.png")
        out_path = Path(result.replace("Image saved to: ", "").strip())
        self.assertEqual(out_path.read_bytes()[:8], _PNG_MAGIC)

    def test_non_image_bytes_returns_error_no_write(self):
        response = _make_fake_response(b"\x00\x01\x02\x03" * 20, text="I can't do that.")
        with self._mock_client(response):
            result = self.mcp_server.generate_image(prompt="x", filename="g_bad.png")
        self.assertNotIn("Image saved to:", result)
        self.assertIn("no valid image", result.lower())
        self.assertIn("I can't do that.", result, msg="Should surface the model's text")
        self.assertFalse((Path(self.output_dir) / "g_bad.png").exists())

    def test_no_image_part_returns_error(self):
        response = _make_fake_response(None, text="here is a description instead")
        with self._mock_client(response):
            result = self.mcp_server.generate_image(prompt="x", filename="g_txt.png")
        self.assertNotIn("Image saved to:", result)
        self.assertIn("no image part", result.lower())

    def test_invalid_model_returns_alias_list(self):
        """A Vertex 'not found' model rejection surfaces the alias map (#350)."""
        err = Exception("404 NOT_FOUND: Model bogus-model was not found")
        with self._mock_client(side_effect=err):
            result = self.mcp_server.generate_image(
                prompt="x", filename="g.png", model="bogus-model"
            )
        payload = json.loads(result)
        self.assertEqual(payload["error"], "invalid_model")
        self.assertEqual(payload["requested_model"], "bogus-model")
        self.assertIn("nano-banana-2", payload["known_aliases"])


class TestEditImageByteHandling(_MockClientMixin, unittest.TestCase):
    """Mock-based branch coverage for edit_image (issue #95). No credentials."""

    def setUp(self):
        super().setUp()
        # A real temp source file — edit_image checks existence before the API call.
        self._source = tempfile.NamedTemporaryFile(
            suffix=".png", dir=self.output_dir, delete=False
        )
        self._source.write(_VALID_FAKE_PNG)
        self._source.flush()
        self._source_path = self._source.name

    def tearDown(self):
        self._source.close()
        super().tearDown()

    def test_bytes_data_writes_valid_png(self):
        response = _make_fake_response(_VALID_FAKE_PNG)
        with self._mock_client(response):
            result = self.mcp_server.edit_image(
                image_path=self._source_path, instruction="make it blue",
                filename="out_bytes.png",
            )
        self.assertIn("Edited image saved to:", result, msg=f"Unexpected: {result}")
        out_path = Path(result.replace("Edited image saved to: ", "").strip())
        self.assertEqual(out_path.read_bytes()[:8], _PNG_MAGIC)

    def test_base64_string_data_writes_valid_png(self):
        b64 = base64.b64encode(_VALID_FAKE_PNG).decode("ascii")
        response = _make_fake_response(b64)
        with self._mock_client(response):
            result = self.mcp_server.edit_image(
                image_path=self._source_path, instruction="make it red",
                filename="out_b64.png",
            )
        self.assertIn("Edited image saved to:", result, msg=f"Unexpected: {result}")
        out_path = Path(result.replace("Edited image saved to: ", "").strip())
        self.assertEqual(out_path.read_bytes()[:8], _PNG_MAGIC)

    def test_corrupt_response_returns_error_with_metadata_no_write(self):
        """Non-image bytes → structured error carrying finish_reason + safety ratings."""
        response = _make_fake_response(
            b"\x00\x01\x02\x03" * 20,
            finish_reason="IMAGE_SAFETY",
            safety_ratings=[_blocked_rating()],
        )
        with self._mock_client(response):
            result = self.mcp_server.edit_image(
                image_path=self._source_path, instruction="make it scary",
                filename="out_corrupt.png",
            )
        self.assertNotIn("Edited image saved to:", result)
        payload = json.loads(result)
        self.assertEqual(payload["error"], "no_image_in_response")
        self.assertIn("safety", payload["message"].lower())
        self.assertIn("no valid image", payload["message"].lower())
        self.assertIn("IMAGE_SAFETY", payload["finish_reason"])
        self.assertTrue(payload["blocked_safety_ratings"])
        # No file written.
        self.assertFalse((Path(self.output_dir) / "out_corrupt.png").exists())

    def test_no_inline_data_returns_error(self):
        response = _make_fake_response(None, text="Sorry, that edit is not allowed.")
        with self._mock_client(response):
            result = self.mcp_server.edit_image(
                image_path=self._source_path, instruction="add sparkles",
                filename="out_none.png",
            )
        self.assertNotIn("Edited image saved to:", result)
        payload = json.loads(result)
        self.assertEqual(payload["error"], "no_image_in_response")
        self.assertIn("no image part", payload["message"].lower())
        self.assertEqual(payload.get("model_text"), "Sorry, that edit is not allowed.")

    def test_hard_block_empty_candidates_returns_error(self):
        """A prompt-level block (no candidates) must not crash — structured error."""
        response = _make_fake_response(None, block_reason="SAFETY", no_candidates=True)
        with self._mock_client(response):
            result = self.mcp_server.edit_image(
                image_path=self._source_path, instruction="do something bad",
                filename="out_block.png",
            )
        self.assertNotIn("Edited image saved to:", result)
        payload = json.loads(result)
        self.assertEqual(payload["error"], "no_image_in_response")
        self.assertIn("SAFETY", payload["block_reason"])
        self.assertFalse((Path(self.output_dir) / "out_block.png").exists())

    def test_missing_source_returns_error_no_api_call(self):
        result = self.mcp_server.edit_image(
            image_path="/nonexistent/image.png", instruction="make it blue",
        )
        self.assertIn("Error: Source image not found", result)

    def test_invalid_model_returns_alias_list(self):
        err = Exception("404 Publisher Model `bad/model` not found")
        with self._mock_client(side_effect=err):
            result = self.mcp_server.edit_image(
                image_path=self._source_path, instruction="x", model="bad-model",
            )
        payload = json.loads(result)
        self.assertEqual(payload["error"], "invalid_model")
        self.assertEqual(payload["resolved_model"], "bad-model")
        self.assertIn("nano-banana-pro", payload["known_aliases"])


class TestModelAliasResolution(unittest.TestCase):
    """Alias → real Vertex model id mapping and passthrough (issue #350)."""

    def setUp(self):
        import mcp_server
        self.mcp_server = mcp_server

    def test_aliases_resolve_to_verified_ids(self):
        r = self.mcp_server._resolve_model
        self.assertEqual(r("nano-banana"), "gemini-2.5-flash-image")
        self.assertEqual(r("nano-banana-2"), "gemini-3.1-flash-image")
        self.assertEqual(r("nano-banana-pro"), "gemini-3-pro-image")

    def test_raw_model_id_passes_through(self):
        self.assertEqual(
            self.mcp_server._resolve_model("gemini-2.5-flash-image"),
            "gemini-2.5-flash-image",
        )
        self.assertEqual(self.mcp_server._resolve_model("some-future-model"), "some-future-model")


class TestMagicByteDetection(unittest.TestCase):
    """Directly exercise the magic-byte guard (issue #95)."""

    def setUp(self):
        import mcp_server
        self._looks = mcp_server._looks_like_image

    def test_accepts_png_and_jpeg(self):
        self.assertTrue(self._looks(_VALID_FAKE_PNG))
        self.assertTrue(self._looks(_VALID_FAKE_JPEG))

    def test_accepts_gif_and_webp(self):
        self.assertTrue(self._looks(b"GIF89a" + b"\x00" * 20))
        self.assertTrue(self._looks(b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20))

    def test_rejects_garbage_and_empty(self):
        self.assertFalse(self._looks(b""))
        self.assertFalse(self._looks(b"\x00\x01\x02\x03"))
        self.assertFalse(self._looks(b"not an image at all"))

    def test_path_traversal_sanitized(self):
        """_save_image strips directory components (regression guard)."""
        import mcp_server
        with patch.object(mcp_server, "OUTPUT_DIR", tempfile.mkdtemp(prefix="gemini_trav_")):
            path = mcp_server._save_image(_VALID_FAKE_PNG, "../../etc/malicious.png")
            self.assertTrue(path.startswith(mcp_server.OUTPUT_DIR))
            self.assertIn("malicious.png", path)
            self.assertNotIn("etc", path)


if __name__ == "__main__":
    unittest.main()
