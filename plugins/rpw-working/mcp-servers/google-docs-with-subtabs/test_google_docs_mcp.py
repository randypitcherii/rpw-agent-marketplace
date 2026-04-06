#!/usr/bin/env python3
"""
Unit tests for Google Docs MCP server safety controls.

Tests read-only mode, allow-list behavior, and audit log without live Google API calls.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

# Ensure we import before any env manipulation
import mcp_server


class TestReadOnlyMode(unittest.TestCase):
    """Read-only mode blocks all mutating tools."""

    def setUp(self):
        self._orig = os.environ.get("GDOCS_READ_ONLY")

    def tearDown(self):
        if self._orig is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def test_read_only_blocks_creates(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        os.environ["GDOCS_QUOTA_PROJECT"] = "test"
        result = mcp_server.gdocs_create("Test", "")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_blocks_updates(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_update("doc123", "content")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_blocks_deletes(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_delete("doc123")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_blocks_add_tab(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_add_tab("doc123", "Tab", "")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_blocks_find_replace(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_find_replace("doc123", "a", "b")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_blocks_write_to_tab(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_write_to_tab("doc123", "tab1", "content")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_blocks_share(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_share("doc123", "a@b.com")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_blocks_insert_person(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_insert_person("doc123", "a@b.com")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_false_allows(self):
        os.environ["GDOCS_READ_ONLY"] = "false"
        self.assertFalse(mcp_server.is_read_only())

    def test_is_read_only_respects_env(self):
        os.environ["GDOCS_READ_ONLY"] = "1"
        self.assertTrue(mcp_server.is_read_only())
        os.environ["GDOCS_READ_ONLY"] = "false"
        self.assertFalse(mcp_server.is_read_only())


class TestAllowList(unittest.TestCase):
    """Allow-list enforcement for folder scope."""

    def setUp(self):
        self._orig_folders = os.environ.get("GDOCS_ALLOWED_FOLDERS")
        self._orig_target = os.environ.get("GDOCS_TARGET_FOLDER_ID")

    def tearDown(self):
        if self._orig_folders is not None:
            os.environ["GDOCS_ALLOWED_FOLDERS"] = self._orig_folders
        elif "GDOCS_ALLOWED_FOLDERS" in os.environ:
            del os.environ["GDOCS_ALLOWED_FOLDERS"]
        if self._orig_target is not None:
            os.environ["GDOCS_TARGET_FOLDER_ID"] = self._orig_target
        elif "GDOCS_TARGET_FOLDER_ID" in os.environ:
            del os.environ["GDOCS_TARGET_FOLDER_ID"]

    def test_empty_allow_list_allows_all(self):
        if "GDOCS_ALLOWED_FOLDERS" in os.environ:
            del os.environ["GDOCS_ALLOWED_FOLDERS"]
        self.assertTrue(mcp_server.is_folder_allowed("any_folder_id"))
        self.assertTrue(mcp_server.is_folder_allowed(""))

    def test_allow_list_includes_folder(self):
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "folder1,folder2,folder3"
        self.assertTrue(mcp_server.is_folder_allowed("folder1"))
        self.assertTrue(mcp_server.is_folder_allowed("folder2"))
        self.assertTrue(mcp_server.is_folder_allowed("folder3"))

    def test_allow_list_excludes_folder(self):
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "folder1,folder2"
        self.assertFalse(mcp_server.is_folder_allowed("folder3"))
        self.assertFalse(mcp_server.is_folder_allowed("other"))

    def test_allow_list_blocks_create_when_target_not_allowed(self):
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ["GDOCS_QUOTA_PROJECT"] = "test"
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "allowed_folder"
        os.environ["GDOCS_TARGET_FOLDER_ID"] = "not_allowed_folder"
        result = mcp_server.gdocs_create("Test", "")
        self.assertIn("error", result)
        self.assertIn("allow-list", result.lower())

    def test_allow_list_allows_create_when_target_allowed(self):
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ["GDOCS_QUOTA_PROJECT"] = "test"
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "allowed_folder"
        os.environ["GDOCS_TARGET_FOLDER_ID"] = "allowed_folder"
        with patch("mcp_server.create_doc") as mock_create:
            mock_create.return_value = {"documentId": "new123", "title": "Test"}
            result = mcp_server.gdocs_create("Test", "")
        self.assertNotIn("error", result)
        mock_create.assert_called_once()


class TestAllowListDocCheck(unittest.TestCase):
    """Allow-list blocks writes to docs not in allowed folders."""

    def setUp(self):
        self._orig = os.environ.get("GDOCS_ALLOWED_FOLDERS")
        os.environ["GDOCS_READ_ONLY"] = "false"

    def tearDown(self):
        if self._orig is not None:
            os.environ["GDOCS_ALLOWED_FOLDERS"] = self._orig
        elif "GDOCS_ALLOWED_FOLDERS" in os.environ:
            del os.environ["GDOCS_ALLOWED_FOLDERS"]

    def test_update_blocked_when_doc_not_in_allowed_folder(self):
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "folder_a"
        with patch("mcp_server._doc_parent_folder") as mock_parent:
            mock_parent.return_value = "folder_b"
            result = mcp_server.gdocs_update("doc123", "content")
        self.assertIn("error", result)
        self.assertIn("allowed", result.lower())

    def test_update_allowed_when_doc_in_allowed_folder(self):
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "folder_a"
        with patch("mcp_server._doc_parent_folder") as mock_parent:
            mock_parent.return_value = "folder_a"
            with patch("mcp_server.update_doc") as mock_update:
                mock_update.return_value = {"status": "updated"}
                result = mcp_server.gdocs_update("doc123", "content")
        self.assertNotIn("error", result)


class TestAuditLog(unittest.TestCase):
    """Audit log appends on mutation."""

    def setUp(self):
        self._orig = os.environ.get("GDOCS_AUDIT_LOG_PATH")
        self._tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log")
        self._tmp.close()
        os.environ["GDOCS_AUDIT_LOG_PATH"] = self._tmp.name
        os.environ["GDOCS_READ_ONLY"] = "false"

    def tearDown(self):
        if self._orig is not None:
            os.environ["GDOCS_AUDIT_LOG_PATH"] = self._orig
        elif "GDOCS_AUDIT_LOG_PATH" in os.environ:
            del os.environ["GDOCS_AUDIT_LOG_PATH"]
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_audit_log_appends_on_update(self):
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)
        with patch("mcp_server.update_doc") as mock_update:
            mock_update.return_value = {"status": "updated"}
            mcp_server.gdocs_update("doc123", "content")
        with open(self._tmp.name) as f:
            lines = f.readlines()
        self.assertGreaterEqual(len(lines), 1)
        self.assertIn("update", lines[0])
        self.assertIn("doc123", lines[0])


if __name__ == "__main__":
    unittest.main()
