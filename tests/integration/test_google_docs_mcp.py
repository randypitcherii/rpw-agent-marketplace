"""Live integration test for Google Docs (with subtabs) MCP server."""

import os
import unittest

from tests.integration.conftest import McpTestClient, make_uv_command, load_env_file, MCP_SERVERS_DIR


class TestGoogleDocsMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_env_file(MCP_SERVERS_DIR / "google-docs-with-subtabs" / "dev.env", required=["GDOCS_QUOTA_PROJECT"])
        cls.client = McpTestClient(
            "google-docs-with-subtabs",
            make_uv_command("google-docs-with-subtabs"),
        )
        cls.client.start()

        cls.tools = cls.client.list_tools()
        cls.tool_names = [t["name"] for t in cls.tools]

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()

    def test_server_lists_tools(self):
        self.assertGreater(len(self.tools), 0, "Server should expose at least one tool")

    def test_read_operation(self):
        list_tool = next(
            (
                n
                for n in self.tool_names
                if "list" in n.lower() or "search" in n.lower()
            ),
            self.tool_names[0],
        )
        result = self.client.call_tool(list_tool, {}, timeout=30)
        self.assertIn("result", result, f"Read failed: {result}")
