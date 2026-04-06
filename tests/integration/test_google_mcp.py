"""Live integration test for Google MCP server (PEX-based, batch JSON output).

The Google PEX server only flushes stdout after stdin EOF, so interactive
request/response is not possible. This class collects all requests, runs
the server once, and returns all responses. Uses newline-delimited JSON
framing for both input and output.
"""

import json
import os
import subprocess
import time
import unittest
from pathlib import Path

from tests.integration.conftest import load_gcloud_adc

PEX_PATH = Path.home() / "mcp" / "servers" / "google_mcp" / "google_mcp_deploy.pex"


class BatchMcpSession:
    """Send a batch of MCP requests, close stdin, read all responses.

    Uses newline-delimited JSON framing (not Content-Length).
    """

    def __init__(self, command: list[str], timeout: float = 60.0):
        self.command = command
        self.timeout = timeout
        self._next_id = 1
        self._messages: list[dict] = []

    def add_request(self, method: str, params: dict) -> int:
        req_id = self._next_id
        self._next_id += 1
        self._messages.append(
            {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        )
        return req_id

    def run(self) -> dict[int, dict]:
        """Execute all requests and return a dict of {id: response}."""
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        # Build payload: initialize + initialized notification + all requests
        init = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-test-client", "version": "1.0.0"},
        }}
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}

        all_msgs = [init, initialized] + self._messages
        payload = b"".join(json.dumps(m).encode() + b"\n" for m in all_msgs)

        stdout_bytes, _stderr_bytes = proc.communicate(input=payload, timeout=self.timeout)

        # Parse bare JSON lines from stdout (skip "Logging to ..." prefix)
        responses: dict[int, dict] = {}
        for line in stdout_bytes.decode(errors="replace").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in msg:
                responses[msg["id"]] = msg

        return responses


class TestGoogleMcp(unittest.TestCase):
    """Integration tests for the Google MCP server.

    Each test creates its own BatchMcpSession (one server invocation per test)
    because the PEX only processes requests in batch mode.
    """

    @classmethod
    def setUpClass(cls):
        if not PEX_PATH.exists():
            raise FileNotFoundError(
                f"Google MCP PEX not found at {PEX_PATH}. "
                "Download it to ~/mcp/servers/google_mcp/google_mcp_deploy.pex first."
            )

        load_gcloud_adc({
            "client_id": "GOOGLE_CLIENT_ID",
            "client_secret": "GOOGLE_CLIENT_SECRET",
            "refresh_token": "GOOGLE_REFRESH_TOKEN",
        })

        os.environ["I_DANGEROUSLY_OPT_IN_TO_UNSUPPORTED_ALPHA_TOOLS"] = "true"
        os.environ["MCP_PRIVACY_SUMMARIZATION_ENABLED"] = "false"

    def _session(self) -> BatchMcpSession:
        # Run PEX directly — bypasses run_mcp.py which would load empty dev.env
        return BatchMcpSession(["python3.10", str(PEX_PATH)], timeout=60)

    def test_server_lists_tools(self):
        session = self._session()
        tools_id = session.add_request("tools/list", {})
        responses = session.run()

        self.assertIn(tools_id, responses, f"No response for tools/list. Got: {list(responses.keys())}")
        result = responses[tools_id]
        self.assertIn("result", result, f"tools/list error: {result}")

        tool_names = [t["name"] for t in result["result"]["tools"]]
        self.assertGreater(len(tool_names), 0)
        self.assertIn("drive_file_list", tool_names)
        self.assertIn("drive_file_create", tool_names)
        self.assertIn("drive_file_delete", tool_names)

    def test_read_operation_list_drive_files(self):
        session = self._session()
        list_id = session.add_request("tools/call", {
            "name": "drive_file_list",
            "arguments": {},
        })
        responses = session.run()

        self.assertIn(list_id, responses, f"No response for drive_file_list. Got: {list(responses.keys())}")
        result = responses[list_id]
        self.assertIn("result", result, f"drive_file_list error: {result}")
        content = result["result"].get("content", [])
        self.assertIsInstance(content, list)

    def test_create_and_delete_drive_file(self):
        timestamp = int(time.time())
        title = f"_mcp_integration_test_{timestamp}"

        session = self._session()
        create_id = session.add_request("tools/call", {
            "name": "drive_file_create",
            "arguments": {
                "name": title,
                "mime_type": "application/vnd.google-apps.document",
            },
        })
        responses = session.run()

        self.assertIn(create_id, responses, f"No response for drive_file_create. Got: {list(responses.keys())}")
        create_result = responses[create_id]
        self.assertIn("result", create_result, f"drive_file_create error: {create_result}")

        # Extract file ID from response content
        content_list = create_result["result"].get("content", [])
        file_id = None
        for item in content_list:
            text = item.get("text", "")
            try:
                parsed = json.loads(text)
                file_id = (
                    parsed.get("file_id")
                    or parsed.get("id")
                    or parsed.get("fileId")
                    or parsed.get("documentId")
                )
            except (json.JSONDecodeError, AttributeError):
                pass
            if file_id:
                break

        self.assertIsNotNone(file_id, f"Could not extract file ID from: {create_result}")

        # Delete in a second session
        del_session = self._session()
        delete_id = del_session.add_request("tools/call", {
            "name": "drive_file_delete",
            "arguments": {"file_id": file_id},
        })
        del_responses = del_session.run()

        self.assertIn(delete_id, del_responses, f"No response for drive_file_delete. Got: {list(del_responses.keys())}")
        delete_result = del_responses[delete_id]
        self.assertIn("result", delete_result, f"drive_file_delete error: {delete_result}")
