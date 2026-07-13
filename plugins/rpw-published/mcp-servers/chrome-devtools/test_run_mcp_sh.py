import json
import os
import subprocess
import unittest


class TestChromeDevtoolsWrapper(unittest.TestCase):
    """Tests for chrome-devtools MCP shell wrapper."""

    def setUp(self):
        self.server_dir = os.path.dirname(os.path.abspath(__file__))
        self.script = os.path.join(self.server_dir, "run_mcp.sh")
        self.sample_config = os.path.join(
            self.server_dir, "chrome-devtools.mcp.json"
        )

    def test_run_mcp_sh_exists_and_executable(self):
        self.assertTrue(os.path.isfile(self.script))
        self.assertTrue(os.access(self.script, os.X_OK))

    def test_sample_config_is_valid_json(self):
        with open(self.sample_config) as f:
            config = json.load(f)
        self.assertIn("mcpServers", config)
        self.assertIn("chrome-devtools", config["mcpServers"])

    def test_sample_config_uses_npx(self):
        with open(self.sample_config) as f:
            config = json.load(f)
        server = config["mcpServers"]["chrome-devtools"]
        self.assertEqual(server["command"], "npx")
        self.assertIn("chrome-devtools-mcp@latest", server["args"])

    def test_script_contains_expected_flags(self):
        with open(self.script) as f:
            content = f.read()
        self.assertIn("--no-category-performance", content)
        self.assertIn("--no-category-emulation", content)
        self.assertIn("chrome-devtools-mcp@latest", content)


if __name__ == "__main__":
    unittest.main()
