"""Tests for the UC connection classifier."""

import unittest

from uc_connection_classify import HTTP_PROXY, MCP_NATIVE, classify, proxy_url


class TestClassify(unittest.TestCase):
    def test_is_mcp_connection_true_string_is_mcp_native(self):
        self.assertEqual(classify({"options": {"is_mcp_connection": "true"}}), MCP_NATIVE)

    def test_is_mcp_connection_false_string_is_http_proxy(self):
        self.assertEqual(classify({"options": {"is_mcp_connection": "false"}}), HTTP_PROXY)

    def test_is_mcp_connection_absent_is_http_proxy(self):
        self.assertEqual(classify({"options": {}}), HTTP_PROXY)

    def test_options_absent_is_http_proxy(self):
        self.assertEqual(classify({}), HTTP_PROXY)

    def test_is_mcp_connection_bool_true_is_http_proxy(self):
        # Databricks returns this as the literal string "true", not a bool.
        # If we ever see a real bool, it's a different shape — treat as HTTP_PROXY
        # rather than guess.
        self.assertEqual(classify({"options": {"is_mcp_connection": True}}), HTTP_PROXY)

    def test_realistic_search_mcp_payload_is_http_proxy(self):
        # Shape based on a `search-mcp` connection observed 2026-05-19.
        conn = {
            "name": "search-mcp",
            "connection_type": "HTTP",
            "options": {
                "base_path": "/rest/api/v1",
                "host": "https://acme-be.example-search.com",
            },
        }
        self.assertEqual(classify(conn), HTTP_PROXY)

    def test_realistic_system_ai_agent_search_mcp_is_mcp_native(self):
        # Shape based on a `system_ai_agent_search_mcp` connection.
        conn = {
            "name": "system_ai_agent_search_mcp",
            "connection_type": "HTTP",
            "options": {"is_mcp_connection": "true"},
        }
        self.assertEqual(classify(conn), MCP_NATIVE)


class TestProxyUrl(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            proxy_url("https://adb-1111222233334444.5.azuredatabricks.net", "search-mcp"),
            "https://adb-1111222233334444.5.azuredatabricks.net/api/2.0/unity-catalog/connections/search-mcp/proxy/",
        )

    def test_trailing_slash_on_host_is_stripped(self):
        self.assertEqual(
            proxy_url("https://workspace.databricks.com/", "slack"),
            "https://workspace.databricks.com/api/2.0/unity-catalog/connections/slack/proxy/",
        )


if __name__ == "__main__":
    unittest.main()
