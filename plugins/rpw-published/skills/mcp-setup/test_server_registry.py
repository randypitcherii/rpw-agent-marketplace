"""Tests for the MCP server registry schema."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from server_registry import SERVERS, PLUGIN_NAME


VALID_SOURCE_TYPES = {"uc_connection", "databricks_secrets", "gcloud_adc", "uc_proxy"}


class TestServerRegistrySchema(unittest.TestCase):
    def test_registry_is_non_empty(self):
        self.assertGreater(len(SERVERS), 0)

    def test_plugin_name_set(self):
        self.assertTrue(PLUGIN_NAME)
        self.assertNotIn(" ", PLUGIN_NAME)
        self.assertNotIn("-", PLUGIN_NAME, "PLUGIN_NAME must use underscores (secret scope convention)")

    def test_every_server_has_sources_list(self):
        for name, entry in SERVERS.items():
            self.assertIn("sources", entry, f"{name} missing sources list")
            self.assertIsInstance(entry["sources"], list, f"{name} sources not a list")
            self.assertGreater(len(entry["sources"]), 0, f"{name} sources is empty")

    def test_every_source_has_valid_type(self):
        for name, entry in SERVERS.items():
            for i, source in enumerate(entry["sources"]):
                self.assertIn(
                    source.get("type"),
                    VALID_SOURCE_TYPES,
                    f"{name} sources[{i}] has invalid type: {source.get('type')}",
                )

    def test_uc_connection_sources_have_connection_name_and_field_map(self):
        for name, entry in SERVERS.items():
            for i, source in enumerate(entry["sources"]):
                if source["type"] != "uc_connection":
                    continue
                self.assertIn("connection_name", source, f"{name} sources[{i}] missing connection_name")
                self.assertIn("field_map", source, f"{name} sources[{i}] missing field_map")
                self.assertIsInstance(source["field_map"], dict)
                self.assertGreater(len(source["field_map"]), 0)

    def test_databricks_secrets_sources_have_secret_map(self):
        for name, entry in SERVERS.items():
            for i, source in enumerate(entry["sources"]):
                if source["type"] != "databricks_secrets":
                    continue
                self.assertIn("secret_map", source, f"{name} sources[{i}] missing secret_map")
                self.assertIsInstance(source["secret_map"], dict)
                self.assertGreater(len(source["secret_map"]), 0)

    def test_gcloud_adc_sources_have_field_map(self):
        for name, entry in SERVERS.items():
            for i, source in enumerate(entry["sources"]):
                if source["type"] != "gcloud_adc":
                    continue
                self.assertIn("field_map", source, f"{name} sources[{i}] missing field_map")
                self.assertIsInstance(source["field_map"], dict)

    def test_uc_proxy_entries_have_connection_name(self):
        for name, entry in SERVERS.items():
            for i, source in enumerate(entry["sources"]):
                if source["type"] != "uc_proxy":
                    continue
                self.assertIn(
                    "connection_name",
                    source,
                    f"{name} sources[{i}] missing connection_name",
                )
                self.assertIsInstance(source["connection_name"], str)
                self.assertTrue(source["connection_name"])

    def test_expected_servers_present(self):
        expected = {
            "slack",
            "jira",
            "glean",
            "gemini-image",
            "google-drive",
            "google-gmail",
            "google-calendar",
            "google-tasks",
            "google-docs",
        }
        self.assertEqual(set(SERVERS.keys()), expected)

    def test_google_split_servers_use_same_uc_proxy_connection(self):
        """google-drive/gmail/calendar must all proxy through the `google-mcp` UC connection."""
        for name in ("google-drive", "google-gmail", "google-calendar"):
            self.assertIn(name, SERVERS, f"missing {name} in registry")
            sources = SERVERS[name]["sources"]
            self.assertEqual(len(sources), 1, f"{name} should have exactly one source")
            self.assertEqual(sources[0]["type"], "uc_proxy")
            self.assertEqual(sources[0]["connection_name"], "google-mcp")

    def test_legacy_google_entry_removed(self):
        """The pre-split 'google' server key must be gone."""
        self.assertNotIn("google", SERVERS)

    def test_sources_env_vars_consistent_across_fallbacks(self):
        """If a server has multiple sources, they must all resolve to the same env vars.

        uc_proxy sources are skipped because they produce a different env var
        shape (UC_PROXY_*) by design — the server uses the SDK to proxy calls
        rather than extracting credentials into app-specific env vars.
        """
        for name, entry in SERVERS.items():
            sources = entry["sources"]
            if len(sources) < 2:
                continue
            env_var_sets = []
            for source in sources:
                if source["type"] == "uc_proxy":
                    continue
                if source["type"] == "uc_connection":
                    env_var_sets.append(set(source["field_map"].values()))
                elif source["type"] == "databricks_secrets":
                    env_var_sets.append(set(source["secret_map"].values()))
                elif source["type"] == "gcloud_adc":
                    env_var_sets.append(set(source["field_map"].values()))
            if len(env_var_sets) < 2:
                continue
            first = env_var_sets[0]
            for i, s in enumerate(env_var_sets[1:], start=1):
                self.assertEqual(
                    s,
                    first,
                    f"{name} sources[{i}] produces different env vars than sources[0]",
                )


if __name__ == "__main__":
    unittest.main()
