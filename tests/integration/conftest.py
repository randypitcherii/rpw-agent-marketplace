"""Shared infrastructure for MCP server live integration tests."""

import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MCP_SERVERS_DIR = REPO_ROOT / "plugins" / "rpw-working" / "mcp-servers"


def load_env_file(env_path: Path, required: list[str] | None = None):
    """Load key=value pairs from an env file into os.environ.

    Simple parser that handles comments, blank lines, and optional quoting.
    No external dependencies required.
    """
    if not env_path.exists():
        raise FileNotFoundError(f"Env file not found: {env_path}")
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'\"")
        os.environ[key] = value
    if required:
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise EnvironmentError(
                f"Missing required env vars: {missing}. "
                f"Check {env_path}"
            )


def load_gcloud_adc(env_var_map: dict[str, str]):
    """Load Google ADC credentials into os.environ.

    Reads ~/.config/gcloud/application_default_credentials.json and maps
    fields to environment variable names per env_var_map.
    """
    adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    if not adc_path.exists():
        raise FileNotFoundError(
            f"gcloud ADC not found at {adc_path}. "
            "Run: gcloud auth application-default login"
        )
    adc = json.loads(adc_path.read_text())
    for adc_field, env_var in env_var_map.items():
        if adc_field in adc:
            os.environ[env_var] = adc[adc_field]
    missing = [v for v in env_var_map.values() if not os.environ.get(v)]
    if missing:
        raise EnvironmentError(f"Missing ADC fields for env vars: {missing}")


class McpTestClient:
    """Starts an MCP server over stdio and sends JSON-RPC messages.

    Uses newline-delimited JSON framing, which is the format used by the
    mcp SDK's stdio_server transport (mcp.server.stdio).
    """

    def __init__(self, server_name: str, command: list[str], cwd: Path | None = None):
        self.server_name = server_name
        self.command = command
        self.cwd = cwd
        self.process: subprocess.Popen | None = None
        self._request_id = 0
        self._stdout_buf = b""

    def start(self, timeout: float = 30.0):
        """Start the MCP server subprocess."""
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
        )
        # Send initialize request
        response = self.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-test-client", "version": "1.0.0"},
        }, timeout=timeout)
        assert "result" in response, f"Initialize failed: {response}"
        # Send initialized notification
        self._send_notification("notifications/initialized", {})
        return response

    def send(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        """Send a JSON-RPC request and wait for response."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        message = json.dumps(request) + "\n"
        self.process.stdin.write(message.encode())
        self.process.stdin.flush()
        return self._read_response(timeout)

    def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        message = json.dumps(notification) + "\n"
        self.process.stdin.write(message.encode())
        self.process.stdin.flush()

    def _read_line(self, deadline: float) -> bytes | None:
        """Read one newline-terminated line from stdout, using internal buffer."""
        while True:
            # Check if we already have a complete line in the buffer
            newline_pos = self._stdout_buf.find(b"\n")
            if newline_pos != -1:
                line = self._stdout_buf[:newline_pos]
                self._stdout_buf = self._stdout_buf[newline_pos + 1:]
                return line.strip()

            # Need more data
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([self.process.stdout], [], [], min(remaining, 1.0))
            if not ready:
                continue
            chunk = self.process.stdout.read1(4096)
            if not chunk:
                # EOF — server died
                stderr = self.process.stderr.read()
                raise RuntimeError(
                    f"MCP server {self.server_name} died. stderr: {stderr.decode()}"
                )
            self._stdout_buf += chunk

    def _read_response(self, timeout: float) -> dict:
        """Read a JSON-RPC response from stdout, skipping notifications."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self._read_line(deadline)
            if line is None:
                raise TimeoutError(f"Timed out waiting for response from {self.server_name}")
            if not line:
                continue
            try:
                parsed = json.loads(line.decode())
            except json.JSONDecodeError:
                continue
            # Skip notifications (no "id" field) — we only want responses
            if "id" in parsed:
                return parsed

        raise TimeoutError(f"Timed out waiting for response from {self.server_name}")

    def list_tools(self) -> list[dict]:
        """Send tools/list and return the tools array."""
        response = self.send("tools/list", {})
        assert "result" in response, f"tools/list failed: {response}"
        return response["result"]["tools"]

    def call_tool(self, name: str, arguments: dict, timeout: float = 30.0) -> dict:
        """Send tools/call and return the result."""
        response = self.send("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        return response

    def stop(self):
        """Kill the MCP server subprocess."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


DEFAULT_DATABRICKS_PROFILE = os.environ.get("DATABRICKS_MCP_PROFILE", "logfood")


def get_databricks_profile(connection: str | None = None) -> str:
    """Return the Databricks profile for a given connection name.

    Checks DATABRICKS_MCP_PROFILE_<CONNECTION> first (uppercased, hyphens→underscores),
    then falls back to DATABRICKS_MCP_PROFILE, then to "logfood".
    """
    if connection:
        env_key = "DATABRICKS_MCP_PROFILE_" + connection.upper().replace("-", "_")
        override = os.environ.get(env_key)
        if override:
            return override
    return DEFAULT_DATABRICKS_PROFILE


def proxy_request(
    connection_name: str,
    method: str,
    path: str,
    body: dict | None = None,
    profile: str | None = None,
) -> dict:
    """Call a service API through the Databricks UC Connection proxy.

    Uses the per-connection profile override if set, otherwise falls back to
    the configured default (DATABRICKS_MCP_PROFILE env var, or "logfood").
    """
    resolved_profile = profile if profile is not None else get_databricks_profile(connection_name)
    payload = {
        "connection_name": connection_name,
        "method": method,
        "path": path,
    }
    if body is not None:
        payload["body"] = json.dumps(body)

    result = subprocess.run(
        [
            "databricks", "api", "post",
            "/api/2.0/external-function-request",
            "--json", json.dumps(payload),
            "--profile", resolved_profile,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Databricks CLI failed (rc={result.returncode}): {result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Non-JSON response from proxy: {result.stdout[:500]}")


def make_uv_command(server_dir: str) -> list[str]:
    """Build the uv run command for an MCP server.

    Uses the venv's own python directly when available to avoid uv resolving
    an incompatible Python from the calling environment's PATH.
    """
    server_path = MCP_SERVERS_DIR / server_dir
    venv_python = server_path / ".venv" / "bin" / "python"
    if venv_python.exists():
        return [str(venv_python), str(server_path / "run_mcp.py")]
    return [
        "uv", "run",
        "--project", str(server_path),
        "python", str(server_path / "run_mcp.py"),
    ]
