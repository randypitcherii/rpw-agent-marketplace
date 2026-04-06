"""Live integration test for gemini-image MCP server."""

import unittest
from pathlib import Path

from tests.integration.conftest import McpTestClient, make_uv_command, load_env_file, MCP_SERVERS_DIR


class TestGeminiImageMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_env_file(
            MCP_SERVERS_DIR / "gemini-image" / "dev.env",
            required=["GEMINI_API_KEY"],
        )
        cls.client = McpTestClient("gemini-image", make_uv_command("gemini-image"))
        cls.client.start()

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0, "Server should expose at least one tool")
        tool_names = [t["name"] for t in tools]
        # Verify there's an image-related tool
        self.assertTrue(
            any("image" in n.lower() or "generat" in n.lower() for n in tool_names),
            f"Expected an image generation tool, got: {tool_names}",
        )

    def test_generate_image(self):
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]
        gen_tool = next(
            (n for n in tool_names if "image" in n.lower() or "generat" in n.lower()),
            tool_names[0],
        )
        result = self.client.call_tool(gen_tool, {
            "prompt": "A small red circle on white background",
        }, timeout=60)
        self.assertIn("result", result, f"Tool call failed: {result}")
