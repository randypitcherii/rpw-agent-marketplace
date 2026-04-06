"""Live integration test for Jira via Databricks UC Connection proxy.

Tests Jira API access through the Databricks external-function endpoint,
which handles OAuth token management via the 'jira-mcp' UC connection.
No PEX server or local credentials required — just a valid Databricks CLI profile.
"""

import unittest

from tests.integration.conftest import get_databricks_profile, proxy_request

CONNECTION_NAME = "jira-mcp"


def _proxy_request(method: str, path: str, body: dict | None = None, profile: str | None = None) -> dict:
    """Call Jira API through the Databricks UC Connection proxy."""
    return proxy_request(CONNECTION_NAME, method, path, body=body, profile=profile)


class TestJiraProxy(unittest.TestCase):
    """Integration tests for Jira via Databricks UC Connection proxy."""

    def test_list_projects(self):
        """List Jira projects (read operation)."""
        resp = _proxy_request("GET", "/project")
        # /project returns a list of project objects
        self.assertIsInstance(resp, list, f"Expected list of projects, got: {type(resp)}")
        self.assertGreater(len(resp), 0, "Expected at least one Jira project")
        # Each project should have key and name
        first = resp[0]
        self.assertIn("key", first, f"Expected 'key' in project: {first}")
        self.assertIn("name", first, f"Expected 'name' in project: {first}")

    def test_get_server_info(self):
        """Get Jira server info (lightweight read operation)."""
        resp = _proxy_request("GET", "/serverInfo")
        self.assertIn(
            "baseUrl", resp,
            f"Expected 'baseUrl' in serverInfo response: {list(resp.keys())}"
        )
