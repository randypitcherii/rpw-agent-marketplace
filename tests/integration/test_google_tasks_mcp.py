"""Live integration test for Google Tasks MCP server."""

import json
import os
import time
import unittest
from pathlib import Path

from tests.integration.conftest import McpTestClient, make_uv_command, load_gcloud_adc, MCP_SERVERS_DIR


class TestGoogleTasksMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_gcloud_adc({
            "client_id": "GOOGLE_CLIENT_ID",
            "client_secret": "GOOGLE_CLIENT_SECRET",
            "refresh_token": "GOOGLE_REFRESH_TOKEN",
        })
        # Suppress FastMCP startup banner from stdout (would break JSON-RPC reader)
        os.environ["FASTMCP_SHOW_SERVER_BANNER"] = "false"
        server_dir = MCP_SERVERS_DIR / "google-tasks"
        cls.client = McpTestClient(
            "google-tasks", make_uv_command("google-tasks"), cwd=server_dir
        )
        cls.client.start()

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0, "Server should expose at least one tool")
        tool_names = [t["name"] for t in tools]
        self.assertIn(
            "gtasks_list_tasklists",
            tool_names,
            f"Expected gtasks_list_tasklists in tools, got: {tool_names}",
        )
        self.assertIn(
            "gtasks_create_task",
            tool_names,
            f"Expected gtasks_create_task in tools, got: {tool_names}",
        )
        self.assertIn(
            "gtasks_delete_task",
            tool_names,
            f"Expected gtasks_delete_task in tools, got: {tool_names}",
        )

    def test_list_tasklists(self):
        result = self.client.call_tool("gtasks_list_tasklists", {})
        self.assertIn("result", result, f"Tool call failed: {result}")
        content = result["result"].get("content", [])
        self.assertTrue(len(content) > 0, f"Expected non-empty content, got: {result}")
        text = content[0].get("text", "")
        data = json.loads(text)
        self.assertIn("tasklists", data, f"Expected 'tasklists' key in response: {data}")
        tasklists = data["tasklists"]
        self.assertIsInstance(tasklists, list, f"Expected tasklists to be a list: {data}")

    def test_create_and_delete_task(self):
        timestamp = int(time.time())
        title = f"_mcp_integration_test_{timestamp}"
        created_task_id = None

        try:
            # Create the task
            create_result = self.client.call_tool(
                "gtasks_create_task",
                {"title": title, "tasklist_id": "@default"},
            )
            self.assertIn("result", create_result, f"Create task failed: {create_result}")
            content = create_result["result"].get("content", [])
            self.assertTrue(len(content) > 0, f"Expected content in create result: {create_result}")
            data = json.loads(content[0]["text"])
            self.assertEqual(data.get("status"), "created", f"Unexpected create status: {data}")
            self.assertIn("id", data, f"Expected task ID in create response: {data}")
            created_task_id = data["id"]
        finally:
            # Clean up: delete the task if it was created
            if created_task_id:
                delete_result = self.client.call_tool(
                    "gtasks_delete_task",
                    {"tasklist_id": "@default", "task_id": created_task_id},
                )
                self.assertIn("result", delete_result, f"Delete task failed: {delete_result}")
                content = delete_result["result"].get("content", [])
                data = json.loads(content[0]["text"])
                self.assertEqual(
                    data.get("status"), "deleted", f"Unexpected delete status: {data}"
                )
