"""Live integration test for Glean via Databricks UC Connection proxy.

Tests Glean API access through the Databricks external-function endpoint,
which handles OAuth token management via the 'glean-mcp' UC connection.
No PEX server or local credentials required — just a valid Databricks CLI profile.
"""

import json
import unittest

from tests.integration.conftest import get_databricks_profile, proxy_request

CONNECTION_NAME = "glean-mcp"


def _proxy_request(method: str, path: str, body: dict | None = None, profile: str | None = None) -> dict:
    """Call Glean API through the Databricks UC Connection proxy."""
    return proxy_request(CONNECTION_NAME, method, path, body=body, profile=profile)


class TestGleanProxy(unittest.TestCase):
    """Integration tests for Glean via Databricks UC Connection proxy.

    NOTE: The glean-mcp UC connection has a known Okta OAuth issue
    ("Invalid Secret / Not allowed"). Tests will fail until the
    connection is re-configured by a Databricks workspace admin.
    """

    def _try_proxy(self, method: str, path: str, body: dict | None = None) -> dict:
        """Call proxy, skipping test if connection is broken."""
        try:
            return _proxy_request(method, path, body)
        except RuntimeError as e:
            err = str(e)
            if any(msg in err for msg in ("Invalid Secret", "Not allowed", "404", "401", "403")):
                self.skipTest(
                    f"Glean UC connection error — needs admin re-configuration "
                    f"on logfood workspace. Error: {err[:200]}"
                )
            raise

    def test_search(self):
        """Run a basic search query through the Glean API."""
        resp = self._try_proxy("POST", "/search", {
            "query": "databricks",
            "pageSize": 3,
        })
        self.assertIn(
            "results", resp,
            f"Expected 'results' key in search response. Got keys: {list(resp.keys())}. "
            f"Full response: {json.dumps(resp)[:500]}"
        )

    def test_person_lookup(self):
        """Look up a person in the Glean directory."""
        resp = self._try_proxy("POST", "/people/search", {
            "query": "randy pitcher",
            "pageSize": 1,
        })
        results = resp.get("results", [])
        self.assertGreater(
            len(results), 0,
            f"Expected at least one person result for 'randy pitcher': {resp}"
        )
