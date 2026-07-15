"""Unit tests: imessage MCP -> `imsg` CLI argument shaping and the read-only /
send-only security boundaries (TDD). Fully mocked — no Full Disk Access required,
no real messages sent.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import mcp_server


def _ok_proc(stdout: str = '{"ok": true}') -> MagicMock:
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = stdout
    proc.stderr = ""
    return proc


class ShapingBase(unittest.TestCase):
    def setUp(self):
        self._patcher = patch("mcp_server.subprocess.run", return_value=_ok_proc())
        self.run = self._patcher.start()
        # Pin the binary so tests don't depend on PATH.
        self._bin = patch.object(mcp_server, "_IMSG", "imsg")
        self._bin.start()

    def tearDown(self):
        self._patcher.stop()
        self._bin.stop()

    def _argv(self):
        """The argv list passed to subprocess.run for the last call."""
        return self.run.call_args[0][0]


class TestReadTools(ShapingBase):
    def test_search_shapes_query_match_limit_and_json(self):
        mcp_server.imessage_search("pizza tonight", match="exact", limit=10)
        argv = self._argv()
        self.assertEqual(argv[0], "imsg")
        self.assertEqual(argv[1], "search")
        self.assertIn("--query", argv)
        self.assertEqual(argv[argv.index("--query") + 1], "pizza tonight")
        self.assertEqual(argv[argv.index("--match") + 1], "exact")
        self.assertEqual(argv[argv.index("--limit") + 1], "10")
        self.assertIn("--json", argv)

    def test_search_clamps_limit_and_defaults_bad_match(self):
        mcp_server.imessage_search("hi", match="bogus", limit=9999)
        argv = self._argv()
        self.assertEqual(argv[argv.index("--limit") + 1], "200")
        self.assertEqual(argv[argv.index("--match") + 1], "contains")

    def test_search_rejects_empty_query_without_invoking_imsg(self):
        out = json.loads(mcp_server.imessage_search("   "))
        self.assertFalse(out["success"])
        self.run.assert_not_called()

    def test_list_chats_uses_chats_subcommand(self):
        mcp_server.imessage_list_chats(limit=5)
        argv = self._argv()
        self.assertEqual(argv[1], "chats")
        self.assertEqual(argv[argv.index("--limit") + 1], "5")
        self.assertIn("--json", argv)

    def test_recent_by_chat_id(self):
        mcp_server.imessage_recent(chat_id=14, limit=30)
        argv = self._argv()
        self.assertEqual(argv[1], "history")
        self.assertEqual(argv[argv.index("--chat-id") + 1], "14")

    def test_recent_by_participants_and_bounds(self):
        mcp_server.imessage_recent(
            participants="+12025550123",
            start="2026-01-01T00:00:00Z",
            end="2026-02-01T00:00:00Z",
        )
        argv = self._argv()
        self.assertEqual(argv[argv.index("--participants") + 1], "+12025550123")
        self.assertEqual(argv[argv.index("--start") + 1], "2026-01-01T00:00:00Z")
        self.assertEqual(argv[argv.index("--end") + 1], "2026-02-01T00:00:00Z")

    def test_recent_requires_a_selector(self):
        out = json.loads(mcp_server.imessage_recent())
        self.assertFalse(out["success"])
        self.run.assert_not_called()


class TestReadOnlyBoundary(ShapingBase):
    def test_read_tools_never_invoke_a_write_subcommand(self):
        """Every read tool must invoke only search/history/chats."""
        mcp_server.imessage_search("x")
        mcp_server.imessage_list_chats()
        mcp_server.imessage_recent(chat_id=1)
        for call in self.run.call_args_list:
            subcommand = call[0][0][1]
            self.assertIn(subcommand, {"search", "history", "chats"})

    def test_run_read_refuses_unknown_subcommand(self):
        out = json.loads(mcp_server._run_read("send", ["--text", "x"]))
        self.assertFalse(out["success"])
        self.run.assert_not_called()


class TestNotifyMeBoundary(ShapingBase):
    def test_notify_me_targets_configured_handle_only(self):
        with patch.object(mcp_server, "_NOTIFY_ME_HANDLE", "+12025550123"), patch.object(
            mcp_server, "_NOTIFY_ME_SERVICE", "imessage"
        ):
            mcp_server.imessage_notify_me("build finished")
        argv = self._argv()
        self.assertEqual(argv[1], "send")
        self.assertEqual(argv[argv.index("--to") + 1], "+12025550123")
        self.assertEqual(argv[argv.index("--text") + 1], "build finished")
        self.assertEqual(argv[argv.index("--service") + 1], "imessage")

    def test_notify_me_has_no_recipient_parameter(self):
        """The tool must expose no way to choose a recipient."""
        import inspect

        params = set(inspect.signature(mcp_server.imessage_notify_me).parameters)
        self.assertEqual(params, {"text"})

    def test_notify_me_errors_when_handle_unconfigured(self):
        with patch.object(mcp_server, "_NOTIFY_ME_HANDLE", ""):
            out = json.loads(mcp_server.imessage_notify_me("hi"))
        self.assertFalse(out["success"])
        self.run.assert_not_called()

    def test_notify_me_rejects_empty_text(self):
        with patch.object(mcp_server, "_NOTIFY_ME_HANDLE", "+12025550123"):
            out = json.loads(mcp_server.imessage_notify_me("  "))
        self.assertFalse(out["success"])
        self.run.assert_not_called()


class TestErrorShaping(ShapingBase):
    def test_nonzero_exit_returns_json_error_with_hint(self):
        self.run.return_value = MagicMock(
            returncode=1, stdout="", stderr="operation not permitted"
        )
        out = json.loads(mcp_server.imessage_list_chats())
        self.assertFalse(out["success"])
        self.assertIn("operation not permitted", out["detail"])
        self.assertIn("Full Disk Access", out["hint"])

    def test_missing_binary_returns_actionable_error(self):
        self.run.side_effect = FileNotFoundError()
        out = json.loads(mcp_server.imessage_search("x"))
        self.assertFalse(out["success"])
        self.assertIn("brew install", out["error"])


if __name__ == "__main__":
    unittest.main()
