"""Fully-mocked tests for the Databricks Foundation Model API backend (#2563).

``GEMINI_IMAGE_BACKEND=databricks`` routes both tools through the Databricks-hosted
Gemini image endpoints (``databricks-gemini-3-1-flash-image`` /
``databricks-gemini-3-pro-image``) with Databricks OAuth — no Google credential.
These tests patch the single HTTP seam (``_databricks_invoke``) so they need no
credentials or network and run in the ``make check`` gate.

The response shapes below are copied from live probes recorded on #2563:
an OpenAI-style chat completion whose ``content`` is a list of parts, the image
as a ``data:image/png;base64,...`` ``image_url`` part.

Run: uv run --with fastmcp --with google-genai --with python-dotenv \
    python -m unittest test_databricks_backend -v
"""

import base64
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
_PNG_2 = b"\x89PNG\r\n\x1a\n" + b"\x01" * 200


def _image_part(data: bytes) -> dict:
    return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(data).decode()}}


def _completion(content, finish_reason="stop", model="gemini-3.1-flash-image") -> dict:
    return {
        "model": model,
        "object": "chat.completion",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 1120, "image_output_tokens": 1120},
    }


class _DatabricksBackendMixin:
    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="gemini_dbx_test_")
        self._env = patch.dict(
            os.environ,
            {"GEMINI_IMAGE_OUTPUT_DIR": self.output_dir, "GEMINI_IMAGE_BACKEND": "databricks",
             "GEMINI_IMAGE_DATABRICKS_PROFILE": "my-profile"},
        )
        self._env.start()
        import mcp_server

        mcp_server.OUTPUT_DIR = self.output_dir
        mcp_server._STALE_AUTH_DATABRICKS.reset()
        self.m = mcp_server

    def tearDown(self):
        self._env.stop()
        for f in Path(self.output_dir).iterdir():
            f.unlink()
        Path(self.output_dir).rmdir()

    def _invoke(self, response=None, side_effect=None):
        kwargs = {"side_effect": side_effect} if side_effect is not None else {"return_value": response}
        return patch.object(self.m, "_databricks_invoke", **kwargs)


class TestBackendSelection(unittest.TestCase):
    def test_default_backend_is_vertex(self):
        import mcp_server

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(mcp_server._backend(), "vertex")

    def test_databricks_backend_selected_case_insensitively(self):
        import mcp_server

        with patch.dict(os.environ, {"GEMINI_IMAGE_BACKEND": " Databricks "}, clear=True):
            self.assertEqual(mcp_server._backend(), "databricks")

    def test_unknown_backend_is_an_error_not_a_silent_fallback(self):
        import mcp_server

        with patch.dict(os.environ, {"GEMINI_IMAGE_BACKEND": "openai"}, clear=True):
            with self.assertRaises(ValueError):
                mcp_server._backend()


class TestDatabricksModelResolution(unittest.TestCase):
    def test_aliases_and_vertex_ids_map_to_endpoints(self):
        import mcp_server

        r = mcp_server._resolve_databricks_endpoint
        self.assertEqual(r("nano-banana-2"), "databricks-gemini-3-1-flash-image")
        self.assertEqual(r("gemini-3.1-flash-image"), "databricks-gemini-3-1-flash-image")
        self.assertEqual(r("nano-banana-pro"), "databricks-gemini-3-pro-image")
        self.assertEqual(r("gemini-3-pro-image"), "databricks-gemini-3-pro-image")

    def test_default_model_maps_to_flash_image(self):
        """Gemini 2.5 Flash Image is not hosted on Databricks; the default must still work."""
        import mcp_server

        self.assertEqual(mcp_server._resolve_databricks_endpoint(mcp_server.DEFAULT_MODEL),
                         "databricks-gemini-3-1-flash-image")
        self.assertEqual(mcp_server._resolve_databricks_endpoint("nano-banana"),
                         "databricks-gemini-3-1-flash-image")

    def test_raw_endpoint_name_passes_through(self):
        import mcp_server

        self.assertEqual(mcp_server._resolve_databricks_endpoint("my-custom-image-endpoint"),
                         "my-custom-image-endpoint")


class TestDatabricksGenerate(_DatabricksBackendMixin, unittest.TestCase):
    def test_image_written_and_request_shape(self):
        with self._invoke(_completion([_image_part(_PNG)])) as inv:
            result = self.m.generate_image(prompt="dunes", filename="d.png", aspect_ratio="16:9", model="nano-banana-2")
        self.assertIn("Image saved to:", result)
        path = Path(result.splitlines()[0].split("Image saved to:", 1)[1].strip())
        self.assertEqual(path.read_bytes(), _PNG)
        endpoint, body = inv.call_args.args
        self.assertEqual(endpoint, "databricks-gemini-3-1-flash-image")
        self.assertEqual(body["messages"], [{"role": "user", "content": "dunes"}])
        # Top-level image_config is forwarded into Gemini generation_config (probed live).
        self.assertEqual(body["image_config"], {"aspect_ratio": "16:9"})
        self.assertNotIn("extra_body", body)

    def test_last_image_wins(self):
        """Pro returns a draft image then the final one — keep the final (probed live)."""
        content = [{"type": "reasoning", "summary": []}, _image_part(_PNG),
                   {"type": "reasoning", "summary": []}, _image_part(_PNG_2)]
        with self._invoke(_completion(content, model="gemini-3-pro-image")):
            result = self.m.generate_image(prompt="x", filename="p.png", model="nano-banana-pro")
        path = Path(result.splitlines()[0].split("Image saved to:", 1)[1].strip())
        self.assertEqual(path.read_bytes(), _PNG_2)

    def test_safety_block_returns_structured_error_and_writes_nothing(self):
        """Live shape of a blocked prompt: empty text part, finish_reason 'error'."""
        with self._invoke(_completion([{"type": "text", "text": ""}], finish_reason="error")):
            result = self.m.generate_image(prompt="blocked", filename="b.png")
        env = json.loads(result)
        self.assertEqual(env["error"], "no_image_in_response")
        self.assertEqual(env["finish_reason"], "error")
        self.assertEqual(env["backend"], "databricks")
        self.assertEqual(list(Path(self.output_dir).iterdir()), [])

    def test_text_only_refusal_surfaces_model_text(self):
        with self._invoke(_completion("I can't make that image.")):
            result = self.m.generate_image(prompt="x", filename="t.png")
        env = json.loads(result)
        self.assertEqual(env["error"], "no_image_in_response")
        self.assertIn("can't make", env["model_text"])

    def test_non_image_bytes_are_rejected(self):
        with self._invoke(_completion([_image_part(b"not an image at all, honestly")])):
            result = self.m.generate_image(prompt="x", filename="n.png")
        env = json.loads(result)
        self.assertEqual(env["error"], "no_image_in_response")
        self.assertEqual(list(Path(self.output_dir).iterdir()), [])

    def test_missing_endpoint_is_invalid_model_with_endpoint_list(self):
        err = RuntimeError("The given endpoint does not exist, please retry after checking the specified model")
        with self._invoke(side_effect=err):
            result = self.m.generate_image(prompt="x", filename="m.png")
        env = json.loads(result)
        self.assertEqual(env["error"], "invalid_model")
        self.assertEqual(env["resolved_model"], "databricks-gemini-3-1-flash-image")
        self.assertIn("cross", env["next_action"].lower())  # names the cross-Geo fix

    def test_expired_databricks_token_latches_stale_auth(self):
        err = RuntimeError("A new access token could not be retrieved because the refresh token is invalid.")
        with self._invoke(side_effect=err) as inv:
            first = self.m.generate_image(prompt="x", filename="s.png")
            second = self.m.generate_image(prompt="x", filename="s.png")
        self.assertIn("databricks auth login --profile my-profile", first)
        self.assertEqual(inv.call_count, 1)  # second call short-circuited
        self.assertIn("databricks auth login", second)


class TestDatabricksEdit(_DatabricksBackendMixin, unittest.TestCase):
    def test_edit_sends_image_as_data_url(self):
        src = Path(self.output_dir) / "src.png"
        src.write_bytes(_PNG)
        with self._invoke(_completion([_image_part(_PNG_2)])) as inv:
            result = self.m.edit_image(image_path=str(src), instruction="add a gold line", filename="e.png")
        self.assertIn("Edited image saved to:", result)
        _, body = inv.call_args.args
        parts = body["messages"][0]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "add a gold line"})
        self.assertTrue(parts[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1]), _PNG)


def _usage_line(result: str) -> dict:
    lines = result.splitlines()
    assert len(lines) == 2 and lines[1].startswith("Usage: "), result
    return json.loads(lines[1][len("Usage: "):])


class TestDatabricksUsageAndImageSize(_DatabricksBackendMixin, unittest.TestCase):
    """#2611: usage reaches the caller; image_size is validated and forwarded."""

    def test_usage_line_carries_image_output_tokens_and_resolved_model(self):
        with self._invoke(_completion([_image_part(_PNG)])):
            result = self.m.generate_image(prompt="x", filename="u.png")
        self.assertTrue(result.splitlines()[0].startswith("Image saved to: "))
        usage = _usage_line(result)
        self.assertEqual(usage["image_output_tokens"], 1120)
        self.assertEqual(usage["prompt_tokens"], 11)
        self.assertEqual(usage["backend"], "databricks")
        # The default model's Databricks resolution is visible, not silent.
        self.assertEqual(usage["requested_model"], "gemini-2.5-flash-image")
        self.assertEqual(usage["resolved_model"], "databricks-gemini-3-1-flash-image")

    def test_nested_image_tokens_are_lifted(self):
        response = _completion([_image_part(_PNG)])
        response["usage"] = {"prompt_tokens": 3, "completion_tokens_details": {"image_tokens": 560}}
        with self._invoke(response):
            usage = _usage_line(self.m.generate_image(prompt="x", filename="n.png"))
        self.assertEqual(usage["image_output_tokens"], 560)

    def test_no_usage_block_means_no_usage_line(self):
        response = _completion([_image_part(_PNG)])
        del response["usage"]
        with self._invoke(response):
            result = self.m.generate_image(prompt="x", filename="nu.png")
        self.assertEqual(len(result.splitlines()), 1)

    def test_edit_reports_usage(self):
        src = Path(self.output_dir) / "src.png"
        src.write_bytes(_PNG)
        with self._invoke(_completion([_image_part(_PNG_2)])):
            result = self.m.edit_image(image_path=str(src), instruction="x", filename="e.png")
        self.assertEqual(_usage_line(result)["image_output_tokens"], 1120)

    def test_image_size_forwarded_in_image_config(self):
        with self._invoke(_completion([_image_part(_PNG)])) as inv:
            self.m.generate_image(prompt="x", filename="s.png", model="nano-banana-pro", image_size="2k")
        _, body = inv.call_args.args
        self.assertEqual(body["image_config"], {"aspect_ratio": "1:1", "image_size": "2K"})

    def test_invalid_image_size_is_rejected_before_any_call(self):
        with self._invoke(_completion([_image_part(_PNG)])) as inv:
            result = self.m.generate_image(prompt="x", filename="s.png", image_size="8K")
        self.assertEqual(json.loads(result)["error"], "invalid_image_size")
        inv.assert_not_called()


class TestVertexPathUntouched(unittest.TestCase):
    """The default backend must not touch the Databricks seam."""

    def test_vertex_generate_does_not_call_databricks(self):
        import mcp_server

        with patch.dict(os.environ, {"GEMINI_IMAGE_BACKEND": "vertex"}):
            with patch.object(mcp_server, "_databricks_invoke") as inv, \
                    patch.object(mcp_server, "_get_client", side_effect=RuntimeError("boom")):
                mcp_server._STALE_AUTH.reset()
                result = mcp_server.generate_image(prompt="x")
        inv.assert_not_called()
        self.assertIn("boom", result)


if __name__ == "__main__":
    unittest.main()
