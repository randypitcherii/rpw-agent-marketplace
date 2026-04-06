"""Live integration test for Slack via Databricks UC Connection proxy.

Tests Slack API access through the Databricks external-function endpoint,
which handles OAuth token management via the 'slack' UC connection.
No PEX server or local credentials required — just a valid Databricks CLI profile.
"""

import unittest

from tests.integration.conftest import get_databricks_profile, proxy_request

CONNECTION_NAME = "slack"


def _proxy_request(method: str, path: str, body: dict | None = None, profile: str | None = None) -> dict:
    """Call Slack API through the Databricks UC Connection proxy."""
    return proxy_request(CONNECTION_NAME, method, path, body=body, profile=profile)


class TestSlackProxy(unittest.TestCase):
    """Integration tests for Slack via Databricks UC Connection proxy."""

    def test_auth_test(self):
        """Verify the Slack connection is authenticated."""
        resp = _proxy_request("GET", "/auth.test")
        self.assertTrue(resp.get("ok"), f"auth.test failed: {resp}")
        self.assertIn("user", resp, f"Expected 'user' in auth.test response: {resp}")

    def test_list_channels(self):
        """List Slack channels (read operation)."""
        resp = _proxy_request("GET", "/conversations.list?limit=3&types=public_channel")
        self.assertTrue(resp.get("ok"), f"conversations.list failed: {resp}")
        channels = resp.get("channels", [])
        self.assertIsInstance(channels, list)
        # Should have at least one channel in a real workspace
        self.assertGreater(len(channels), 0, "Expected at least one channel")

    def test_post_and_delete_message(self):
        """Post a message to a test channel, then delete it (write + cleanup)."""
        # Post to #mcp-test or DM to self — use a safe channel
        # First, find a DM channel by posting to self
        auth = _proxy_request("GET", "/auth.test")
        if not auth.get("ok"):
            self.skipTest(f"Cannot determine bot user: {auth}")

        user_id = auth.get("user_id")
        if not user_id:
            self.skipTest(f"No user_id in auth.test response: {auth}")

        # Open a DM with self
        dm_resp = _proxy_request("POST", "/conversations.open", {"users": user_id})
        if not dm_resp.get("ok"):
            self.skipTest(f"Cannot open DM to self: {dm_resp}")

        channel_id = dm_resp["channel"]["id"]

        # Post a test message
        post_resp = _proxy_request("POST", "/chat.postMessage", {
            "channel": channel_id,
            "text": "[rpw-agent-marketplace integration test — safe to ignore]",
        })
        self.assertTrue(post_resp.get("ok"), f"chat.postMessage failed: {post_resp}")
        ts = post_resp.get("ts")
        self.assertIsNotNone(ts, f"No timestamp in post response: {post_resp}")

        # Delete the message (cleanup)
        delete_resp = _proxy_request("POST", "/chat.delete", {
            "channel": channel_id,
            "ts": ts,
        })
        self.assertTrue(delete_resp.get("ok"), f"chat.delete failed: {delete_resp}")
