"""Tests for the uc_proxy resolver's flavor-aware env-var emission (#115).

The resolver reads `options.is_mcp_connection` from the connection metadata it
already fetches and emits UC_PROXY_FLAVOR + a flavor-shaped UC_PROXY_URL:
- mcp_native  -> {host}/api/2.0/mcp/external/<name>
- http_proxy  -> {host}/api/2.0/unity-catalog/connections/<name>/proxy/  (default)

Backward-compat is the critical property: absent/unparseable metadata, or any
value other than "true", must keep the historical HTTP_PROXY shape.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib.resolvers import uc_proxy


def _metadata_json(is_mcp=None, extra_options=None):
    options = {"host": "https://upstream.example.com"}
    if is_mcp is not None:
        options["is_mcp_connection"] = is_mcp
    if extra_options:
        options.update(extra_options)
    return json.dumps({"name": "conn", "options": options})


class TestIsMcpNative(unittest.TestCase):
    """Direct tests of the metadata classifier — the backward-compat guard."""

    def test_true_string_is_mcp_native(self):
        self.assertTrue(uc_proxy._is_mcp_native(_metadata_json(is_mcp="true")))

    def test_true_string_case_insensitive(self):
        self.assertTrue(uc_proxy._is_mcp_native(_metadata_json(is_mcp="True")))
        self.assertTrue(uc_proxy._is_mcp_native(_metadata_json(is_mcp="TRUE")))

    def test_false_string_is_http_proxy(self):
        self.assertFalse(uc_proxy._is_mcp_native(_metadata_json(is_mcp="false")))

    def test_absent_flag_is_http_proxy(self):
        """A connection with options but no is_mcp_connection stays HTTP_PROXY."""
        self.assertFalse(uc_proxy._is_mcp_native(_metadata_json()))

    def test_no_options_is_http_proxy(self):
        self.assertFalse(uc_proxy._is_mcp_native(json.dumps({"name": "conn"})))

    def test_null_options_is_http_proxy(self):
        self.assertFalse(
            uc_proxy._is_mcp_native(json.dumps({"name": "conn", "options": None}))
        )

    def test_unparseable_metadata_is_http_proxy(self):
        self.assertFalse(uc_proxy._is_mcp_native("not json at all"))

    def test_empty_string_is_http_proxy(self):
        self.assertFalse(uc_proxy._is_mcp_native(""))

    def test_non_object_json_is_http_proxy(self):
        self.assertFalse(uc_proxy._is_mcp_native("[1, 2, 3]"))


class TestResolveEmitsFlavorEnv(unittest.TestCase):
    """End-to-end: resolve() exports the flavor + shaped URL for each case."""

    def _run_resolve(self, metadata_stdout, connection_name="conn"):
        """Drive resolve() with the metadata `databricks api get` would return.

        The metadata subprocess call is the first (and only) subprocess we care
        about here; credential verification and host resolution are stubbed.
        """
        meta_result = MagicMock()
        meta_result.returncode = 0
        meta_result.stdout = metadata_stdout
        with patch.object(uc_proxy.subprocess, "run", return_value=meta_result), \
             patch.object(
                 uc_proxy.databricks_auth,
                 "get_workspace_host",
                 return_value="https://ws.example.com",
             ), \
             patch.object(uc_proxy, "_verify_user_credential_active"), \
             patch.dict(os.environ, {}, clear=True):
            uc_proxy.resolve(connection_name, "test-profile")
            return dict(os.environ)

    def test_mcp_native_connection_emits_mcp_external_url(self):
        env = self._run_resolve(
            _metadata_json(is_mcp="true"), connection_name="system_ai_agent_glean_mcp"
        )
        self.assertEqual(env["UC_PROXY_FLAVOR"], "mcp_native")
        self.assertEqual(
            env["UC_PROXY_URL"],
            "https://ws.example.com/api/2.0/mcp/external/system_ai_agent_glean_mcp",
        )
        self.assertEqual(env["UC_PROXY_CONNECTION_NAME"], "system_ai_agent_glean_mcp")
        self.assertEqual(env["UC_PROXY_PROFILE"], "test-profile")

    def test_http_proxy_connection_keeps_historical_shape(self):
        env = self._run_resolve(_metadata_json(is_mcp="false"), connection_name="slack")
        self.assertEqual(env["UC_PROXY_FLAVOR"], "http_proxy")
        self.assertEqual(
            env["UC_PROXY_URL"],
            "https://ws.example.com/api/2.0/unity-catalog/connections/slack/proxy/",
        )

    def test_absent_metadata_flag_defaults_to_http_proxy(self):
        """The backward-compat default: no flag -> exact pre-#115 URL shape."""
        env = self._run_resolve(_metadata_json(), connection_name="google-mcp")
        self.assertEqual(env["UC_PROXY_FLAVOR"], "http_proxy")
        self.assertEqual(
            env["UC_PROXY_URL"],
            "https://ws.example.com/api/2.0/unity-catalog/connections/google-mcp/proxy/",
        )

    def test_unparseable_metadata_defaults_to_http_proxy(self):
        env = self._run_resolve("garbage-not-json", connection_name="slack")
        self.assertEqual(env["UC_PROXY_FLAVOR"], "http_proxy")
        self.assertIn(
            "/api/2.0/unity-catalog/connections/slack/proxy/", env["UC_PROXY_URL"]
        )


if __name__ == "__main__":
    unittest.main()
