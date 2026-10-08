#!/usr/bin/env python3
"""
Unit tests for Google Docs MCP server safety controls.

Tests read-only mode, allow-list behavior, and audit log without live Google API calls.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

# Ensure we import before any env manipulation
import auth
import config
import docs_read
import docs_write
import mcp_server
import policy

_GATE_PATCH = None


def setUpModule():
    """This suite tests write paths, not styling: stub the post-write house-style
    gate (#2001) so a mocked write never reaches the real Docs API through it.
    The gate itself is covered by test_style_gate.py."""
    global _GATE_PATCH
    from unittest.mock import patch as _patch
    _GATE_PATCH = _patch("style_gate.apply", return_value={
        "ok": True, "errors": 0, "warnings": 0, "by_rule": {}, "samples": [], "tabId": None, "normalized": 0})
    _GATE_PATCH.start()


def tearDownModule():
    _GATE_PATCH.stop()


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
        result = mcp_server.gdocs_share("doc123", "reader@example.com")
        self.assertIn("error", result)
        self.assertIn("Read-only", result)

    def test_read_only_blocks_insert_person(self):
        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_insert_person("doc123", "reader@example.com")
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
        with patch("policy.doc_parent_folder") as mock_parent:
            mock_parent.return_value = "folder_b"
            result = mcp_server.gdocs_update("doc123", "content")
        self.assertIn("error", result)
        self.assertIn("allowed", result.lower())

    def test_update_allowed_when_doc_in_allowed_folder(self):
        os.environ["GDOCS_ALLOWED_FOLDERS"] = "folder_a"
        with patch("policy.doc_parent_folder") as mock_parent:
            mock_parent.return_value = "folder_a"
            with patch("mcp_server.update_doc") as mock_update:
                mock_update.return_value = {"status": "updated"}
                result = mcp_server.gdocs_update("doc123", "content")
        self.assertNotIn("error", json.loads(result))


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


class TestUploadImage(unittest.TestCase):
    """Tests for gdocs_upload_image tool."""

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def test_upload_image_happy_path(self):
        """Happy path: mocked multipart upload + permission call returns success JSON."""
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
            tmp_path = f.name

        try:
            with patch("policy.multipart_upload") as mock_upload, \
                 patch("policy.api") as mock_api, \
                 patch("policy.doc_parent_folder") as mock_parent:
                mock_parent.return_value = "folder123"
                mock_upload.return_value = {"id": "file_abc123"}
                mock_api.return_value = {"id": "perm123"}

                result = mcp_server.gdocs_upload_image("doc1", tmp_path)
                data = json.loads(result)

            self.assertTrue(data.get("ok"))
            self.assertEqual(data["file_id"], "file_abc123")
            self.assertIn("file_abc123", data["url"])
            self.assertEqual(data["mime_type"], "image/png")
        finally:
            os.unlink(tmp_path)

    def test_upload_image_rejects_unsupported_extension(self):
        """Rejects file extensions that aren't png/jpg/jpeg/webp."""
        import json

        result = mcp_server.gdocs_upload_image("doc1", "/some/file.gif")
        data = json.loads(result)

        self.assertFalse(data.get("ok"))
        self.assertIn("error", data)
        self.assertIn("gif", data["error"].lower())

    def test_upload_image_missing_file(self):
        """Returns error JSON when local_path doesn't exist."""
        import json

        result = mcp_server.gdocs_upload_image("doc1", "/nonexistent/path/image.png")
        data = json.loads(result)

        self.assertFalse(data.get("ok"))
        self.assertIn("error", data)


class TestInsertImage(unittest.TestCase):
    """Tests for gdocs_insert_image tool."""

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def test_insert_image_happy_path(self):
        """Happy path: mocked _api for batchUpdate returns success."""
        import json

        with patch("policy.api") as mock_api, \
             patch("policy.doc_parent_folder") as mock_parent:
            mock_parent.return_value = None
            mock_api.return_value = {"replies": [{}], "writeControl": {}}

            result = mcp_server.gdocs_insert_image(
                "doc1", "tab1", "https://drive.google.com/uc?id=abc", 5, 200.0, 150.0
            )
            data = json.loads(result)

        self.assertNotIn("error", data)
        mock_api.assert_called_once()

    def test_insert_image_read_only_blocked(self):
        """Honors read-only mode — returns the read-only error."""
        import json

        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_insert_image(
            "doc1", "tab1", "https://drive.google.com/uc?id=abc", 5
        )
        data = json.loads(result)

        self.assertIn("error", data)
        self.assertIn("Read-only", data["error"])

    def test_insert_image_correct_request_body(self):
        """Asserts correct JSON body shape passed to _api (with objectSize)."""
        import json

        with patch("policy.api") as mock_api, \
             patch("policy.doc_parent_folder") as mock_parent:
            mock_parent.return_value = None
            mock_api.return_value = {"replies": [{}]}

            mcp_server.gdocs_insert_image(
                "doc1", "tab1", "https://example.com/img.png", 5, 100.0, 80.0
            )

        call_args = mock_api.call_args
        method = call_args[0][0]
        url = call_args[0][1]
        body = call_args[0][2]

        self.assertEqual(method, "POST")
        self.assertIn("doc1", url)
        self.assertIn("batchUpdate", url)

        requests_list = body["requests"]
        self.assertEqual(len(requests_list), 1)
        inline = requests_list[0]["insertInlineImage"]
        self.assertEqual(inline["location"]["index"], 5)
        self.assertEqual(inline["location"]["tabId"], "tab1")
        self.assertEqual(inline["uri"], "https://example.com/img.png")
        self.assertEqual(inline["objectSize"]["width"]["magnitude"], 100.0)
        self.assertEqual(inline["objectSize"]["width"]["unit"], "PT")
        self.assertEqual(inline["objectSize"]["height"]["magnitude"], 80.0)
        self.assertEqual(inline["objectSize"]["height"]["unit"], "PT")

    def test_insert_image_omits_object_size_when_none(self):
        """objectSize is omitted entirely when both width_pt and height_pt are None."""
        import json

        with patch("policy.api") as mock_api, \
             patch("policy.doc_parent_folder") as mock_parent:
            mock_parent.return_value = None
            mock_api.return_value = {"replies": [{}]}

            mcp_server.gdocs_insert_image(
                "doc1", "tab1", "https://example.com/img.png", 5
            )

        call_args = mock_api.call_args
        body = call_args[0][2]
        inline = body["requests"][0]["insertInlineImage"]
        self.assertNotIn("objectSize", inline)


class TestGdocsOptionalTargetFolder(unittest.TestCase):
    """GDOCS_TARGET_FOLDER_ID is optional: unset skips the move (create) and
    widens the listing to recent Docs across Drive (list)."""

    def test_list_docs_without_folder_lists_recent_docs(self):
        with patch.object(config, "TARGET_FOLDER_ID", ""):
            with patch("auth.api") as mock_api:
                mock_api.return_value = {"files": [{"id": "d1", "name": "Doc"}]}
                out = docs_read.list_docs()
        self.assertEqual(out, [{"id": "d1", "name": "Doc"}])
        url = mock_api.call_args[0][1]
        self.assertNotIn("in+parents", url)
        self.assertIn("mimeType='application/vnd.google-apps.document'", url)

    def test_list_docs_with_folder_stays_folder_scoped(self):
        with patch.object(config, "TARGET_FOLDER_ID", "folder123"):
            with patch("auth.api") as mock_api:
                mock_api.return_value = {"files": []}
                docs_read.list_docs()
        url = mock_api.call_args[0][1]
        self.assertIn("'folder123'+in+parents", url)

    def test_create_doc_without_folder_skips_move_and_reports_created(self):
        with patch.object(config, "TARGET_FOLDER_ID", ""):
            with patch("auth.api") as mock_api:
                mock_api.return_value = {"documentId": "doc9"}
                result = docs_write.create_doc("Test Title")
        self.assertEqual(result["status"], "created")
        self.assertNotIn("moveError", result)
        urls = [c[0][1] for c in mock_api.call_args_list]
        self.assertEqual(len(urls), 1, f"expected only the create call, got: {urls}")
        self.assertNotIn("drive/v3", " ".join(urls))


class TestFindReplaceTabScoping(unittest.TestCase):
    """find_replace scopes to a single tab via tabsCriteria.tabIds, not tabId (#102)."""

    def test_tab_id_emits_tabs_criteria(self):
        from docs_write import find_replace

        with patch("auth.api") as mock_api:
            mock_api.return_value = {"replies": [{"replaceAllText": {"occurrencesChanged": 1}}]}
            find_replace("doc1", "foo", "bar", tab_id="t.abc123")

        body = mock_api.call_args[0][2]
        req = body["requests"][0]["replaceAllText"]
        self.assertNotIn("tabId", req)
        self.assertEqual(req["tabsCriteria"], {"tabIds": ["t.abc123"]})

    def test_no_tab_id_omits_tabs_criteria(self):
        from docs_write import find_replace

        with patch("auth.api") as mock_api:
            mock_api.return_value = {"replies": [{"replaceAllText": {"occurrencesChanged": 1}}]}
            find_replace("doc1", "foo", "bar")

        body = mock_api.call_args[0][2]
        req = body["requests"][0]["replaceAllText"]
        self.assertNotIn("tabsCriteria", req)
        self.assertNotIn("tabId", req)


class TestInsertMarkdownConstructs(unittest.TestCase):
    """_insert_markdown emits correct batchUpdate requests for each markdown construct."""

    def _collect_all_requests(self, mock_api):
        """Flatten all requests across all batched api() calls."""
        all_requests = []
        for call in mock_api.call_args_list:
            body = call[0][2]
            all_requests.extend(body.get("requests", []))
        return all_requests

    def test_unordered_list_emits_create_paragraph_bullets(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "- a\n- b\n- c")

        all_reqs = self._collect_all_requests(mock_api)
        bullet_reqs = [r for r in all_reqs if "createParagraphBullets" in r]
        self.assertGreaterEqual(len(bullet_reqs), 1)
        preset = bullet_reqs[0]["createParagraphBullets"]["bulletPreset"]
        self.assertEqual(preset, config.BULLET_PRESET)
        # Range must cover all 3 items — startIndex < endIndex
        rng = bullet_reqs[0]["createParagraphBullets"]["range"]
        self.assertIn("startIndex", rng)
        self.assertIn("endIndex", rng)
        self.assertLess(rng["startIndex"], rng["endIndex"])

    def test_ordered_list_emits_numbered_preset(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "1. a\n2. b")

        all_reqs = self._collect_all_requests(mock_api)
        bullet_reqs = [r for r in all_reqs if "createParagraphBullets" in r]
        self.assertGreaterEqual(len(bullet_reqs), 1)
        preset = bullet_reqs[0]["createParagraphBullets"]["bulletPreset"]
        self.assertIn("NUMBERED", preset)

    def test_list_after_heading_resets_to_normal_text(self):
        """Regression (#171): list items following a heading must be reset to
        NORMAL_TEXT, else they inherit the preceding HEADING_N paragraph style."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "## Heading\n\n- item one\n- item two\n")

        all_reqs = self._collect_all_requests(mock_api)

        # The list must still emit bullets.
        bullet_reqs = [r for r in all_reqs if "createParagraphBullets" in r]
        self.assertEqual(len(bullet_reqs), 1)
        list_rng = bullet_reqs[0]["createParagraphBullets"]["range"]

        # Every list line must be reset to NORMAL_TEXT (per line, #2001) so the
        # bullets do not inherit HEADING_2 from the preceding heading.
        normal_rngs = [
            (r["updateParagraphStyle"]["range"]["startIndex"], r["updateParagraphStyle"]["range"]["endIndex"])
            for r in all_reqs
            if "updateParagraphStyle" in r
            and r["updateParagraphStyle"].get("paragraphStyle", {}).get("namedStyleType") == "NORMAL_TEXT"
            and r["updateParagraphStyle"]["range"]["startIndex"] >= list_rng["startIndex"]
        ]
        self.assertEqual(normal_rngs[0][0], list_rng["startIndex"])
        self.assertEqual(normal_rngs[-1][1], list_rng["endIndex"])
        self.assertEqual(len(normal_rngs), 2, "one NORMAL_TEXT reset per list line")

    def test_list_item_inline_styles_survive_the_normal_text_reset(self):
        """Live regression (#2001): applying namedStyleType resets a paragraph's text
        runs, so each list line's NORMAL_TEXT reset must come BEFORE its inline
        styles — a list-wide reset after them wiped **bold** and `code` from every
        list item."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "- **bold** and `code`\n- plain\n")
        reqs = self._collect_all_requests(mock_api)
        kinds = [next(iter(r)) for r in reqs]
        resets = [(i, r["updateParagraphStyle"]["range"]) for i, r in enumerate(reqs)
                  if "updateParagraphStyle" in r
                  and "namedStyleType" in r["updateParagraphStyle"]["fields"].split(",")]
        inline = [(i, r["updateTextStyle"]["range"]) for i, r in enumerate(reqs) if "updateTextStyle" in r]
        self.assertEqual(len(inline), 2)

        def covers(outer, inner):
            return outer["startIndex"] <= inner["startIndex"] and inner["endIndex"] <= outer["endIndex"]

        for i, rng in inline:
            covering = [j for j, r in resets if covers(r, rng)]
            self.assertTrue(covering, f"no NORMAL_TEXT reset covers inline range {rng}")
            self.assertTrue(all(j < i for j in covering),
                            f"a named-style reset over {rng} runs after its inline style")
        self.assertLess(max(i for i, _ in inline), kinds.index("createParagraphBullets"))

    def test_nested_list_tab_consumption_shrinks_following_indexes(self):
        """Regression (#298): createParagraphBullets consumes (deletes) the leading
        nesting tabs, so every request emitted after it must use post-consumption
        indexes. Before the fix, a nested list made the NORMAL_TEXT reset — and all
        following content — target indexes past the segment end, failing the whole
        batch live with "Index N must be less than the end index of the referenced
        segment" (the tab's prior content already cleared: destructive)."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            # 3 nesting tabs total: "\tb\n" (1) + "\t\tc\n" (2).
            _insert_markdown("doc1", "- a\n  - b\n    - c\n\nafter\n")

        all_reqs = self._collect_all_requests(mock_api)

        # Inserted list text spans [1, 10) pre-consumption:
        # "a\n"(2) + "\tb\n"(3) + "\t\tc\n"(4). Bullets target the pre-consumption
        # range — the tabs must still exist for Docs to derive nesting levels.
        bullet_rng = [r["createParagraphBullets"]["range"] for r in all_reqs
                      if "createParagraphBullets" in r][0]
        self.assertEqual((bullet_rng["startIndex"], bullet_rng["endIndex"]), (1, 10))

        # The per-line NORMAL_TEXT resets run BEFORE bullets (#2001), so they use
        # pre-consumption ranges: "a\n" [1,3), "\tb\n" [3,6), "\t\tc\n" [6,10).
        normal_rngs = [(r["updateParagraphStyle"]["range"]["startIndex"],
                        r["updateParagraphStyle"]["range"]["endIndex"]) for r in all_reqs
                       if "updateParagraphStyle" in r
                       and r["updateParagraphStyle"].get("paragraphStyle", {}).get("namedStyleType")
                       == "NORMAL_TEXT"][:3]
        self.assertEqual(normal_rngs, [(1, 3), (3, 6), (6, 10)])

        # Content following the list must land at the post-consumption index too:
        # the restored post-list blank paragraph at 7, then "after" at 8.
        inserts = [r["insertText"] for r in all_reqs if "insertText" in r]
        blank = [i for i in inserts if i["text"] == "\n"]
        self.assertEqual(blank[0]["location"]["index"], 7,
                         "the post-list blank must use the post-tab-consumption index")
        after_inserts = [i for i in inserts if i["text"] == "after\n"]
        self.assertEqual(len(after_inserts), 1)
        self.assertEqual(
            after_inserts[0]["location"]["index"], 8,
            "content after a nested list must use the post-tab-consumption index",
        )

    def test_inline_code_uses_courier_new(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "some `code` here")

        all_reqs = self._collect_all_requests(mock_api)
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        font_reqs = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily") == "Courier New"
        ]
        self.assertGreaterEqual(len(font_reqs), 1)

    def test_fenced_code_block_uses_courier_new(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "```python\nprint(1)\n```")

        all_reqs = self._collect_all_requests(mock_api)
        # Find insertText requests
        insert_reqs = [r for r in all_reqs if "insertText" in r]
        inserted_texts = [r["insertText"]["text"] for r in insert_reqs]
        # No backtick markers should appear
        combined = "".join(inserted_texts)
        self.assertNotIn("```", combined)
        self.assertIn("print(1)", combined)

        # Should have Courier New styling
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        font_reqs = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily") == "Courier New"
        ]
        self.assertGreaterEqual(len(font_reqs), 1)

    def test_link_emits_update_text_style_with_url(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "see [docs](https://example.com)")

        all_reqs = self._collect_all_requests(mock_api)
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        link_reqs = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("link", {}).get("url") == "https://example.com"
        ]
        self.assertGreaterEqual(len(link_reqs), 1)

    def test_nested_link_bullet_is_preserved_and_linked(self):
        """Nested list items with links render as bullet lines with hyperlink styling."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "- Parent\n  - [Docs](https://example.com)")

        all_reqs = self._collect_all_requests(mock_api)
        inserted_text = [
            r["insertText"]["text"]
            for r in all_reqs
            if "insertText" in r
        ]
        self.assertIn("Parent\n", inserted_text)
        self.assertIn("\tDocs\n", inserted_text)

        link_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("link", {}).get("url") == "https://example.com"
        ]
        self.assertEqual(len(link_reqs), 1, f"Expected nested bullet link styling; got {link_reqs}")
        self.assertEqual(
            link_reqs[0]["updateTextStyle"]["range"]["startIndex"],
            9,
            "Link range should start after the nested-list tab prefix",
        )

    def test_markdown_image_emits_insert_inline_image(self):
        """A markdown image in prose becomes a Docs inline image, not dropped text."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "Before ![Diagram](https://example.com/diagram.png) after")

        all_reqs = self._collect_all_requests(mock_api)
        image_reqs = [r for r in all_reqs if "insertInlineImage" in r]
        self.assertEqual(len(image_reqs), 1, f"Expected one inline image request; got {image_reqs}")
        inline_image = image_reqs[0]["insertInlineImage"]
        self.assertEqual(inline_image["uri"], "https://example.com/diagram.png")
        self.assertEqual(inline_image["location"]["index"], 8)

    # --- #182: nested inline styles inside links/strong/emphasis -------------

    def test_walk_inlines_recurses_into_link_children_directly(self):
        """#182 root cause: _walk_inlines must recurse into a link token's
        children. This is the shared code path for both paragraphs and table
        cells, so fixing it here closes the table-cell drop too."""
        from markdown_inline import _walk_inlines

        link_token = {
            "type": "link",
            "attrs": {"url": "https://example.com"},
            "children": [{"type": "codespan", "raw": "ai_analyze_sentiment"}],
        }
        reqs = _walk_inlines([link_token], 1, None)
        styles = [r["updateTextStyle"] for r in reqs if "updateTextStyle" in r]
        link = [s for s in styles if s.get("textStyle", {}).get("link")]
        font = [s for s in styles if s.get("textStyle", {}).get("weightedFontFamily")]
        self.assertEqual(len(link), 1, "expected exactly one link style")
        self.assertEqual(len(font), 1, "codespan font inside link must be emitted")
        # link + font must cover the identical range so they stack on the API.
        self.assertEqual(link[0]["range"], font[0]["range"])

    def test_codespan_inside_link_emits_both_link_and_font(self):
        """#182: [`code`](url) applies BOTH the link and the monospace font over
        the same range (end-to-end through _insert_markdown)."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "[`ai_analyze`](https://example.com)")

        all_reqs = self._collect_all_requests(mock_api)
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        link_reqs = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("link", {}).get("url") == "https://example.com"
        ]
        font_reqs = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily") == "Courier New"
        ]
        self.assertGreaterEqual(len(link_reqs), 1, "link styling missing")
        self.assertGreaterEqual(len(font_reqs), 1, "codespan font missing inside link")
        link_rng = link_reqs[0]["updateTextStyle"]["range"]
        font_rng = font_reqs[0]["updateTextStyle"]["range"]
        self.assertEqual(
            (link_rng["startIndex"], link_rng["endIndex"]),
            (font_rng["startIndex"], font_rng["endIndex"]),
            "link and codespan font must cover the same range",
        )

    def test_codespan_link_suppresses_underline(self):
        """#182 3d feedback: a code hyperlink ([`code`](url)) suppresses the default
        link underline — underscores in code clash with it; color carries the link cue."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "[`ai_analyze_sentiment`](https://example.com)")

        all_reqs = self._collect_all_requests(mock_api)
        link_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("link", {}).get("url") == "https://example.com"
        ]
        self.assertGreaterEqual(len(link_reqs), 1)
        ts = link_reqs[0]["updateTextStyle"]
        self.assertIs(ts["textStyle"].get("underline"), False, "code link must set underline=False")
        self.assertIn("underline", ts["fields"], "fields mask must include underline so it sticks")

    def test_plain_text_link_keeps_default_underline(self):
        """A normal text link must NOT force underline off — Docs' default styling stays."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "see [the docs](https://example.com)")

        all_reqs = self._collect_all_requests(mock_api)
        link_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("link", {}).get("url") == "https://example.com"
        ]
        self.assertGreaterEqual(len(link_reqs), 1)
        ts = link_reqs[0]["updateTextStyle"]
        self.assertNotIn("underline", ts["textStyle"], "plain link must not touch underline")
        self.assertEqual(ts["fields"], "link")

    def test_bold_inside_link_emits_both(self):
        """#182: [**bold**](url) applies link AND bold over the link range."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "[**strong**](https://example.com)")

        all_reqs = self._collect_all_requests(mock_api)
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        self.assertTrue(
            any(r["updateTextStyle"].get("textStyle", {}).get("link", {}).get("url") == "https://example.com" for r in style_reqs),
            "link styling missing",
        )
        self.assertTrue(
            any(r["updateTextStyle"].get("textStyle", {}).get("bold") is True for r in style_reqs),
            "bold missing inside link",
        )

    def test_codespan_inside_bold_emits_both(self):
        """#182: **`code`** applies bold AND monospace font — recursion is general
        over container tokens, not links-only."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "**`code`**")

        all_reqs = self._collect_all_requests(mock_api)
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        self.assertTrue(
            any(r["updateTextStyle"].get("textStyle", {}).get("bold") is True for r in style_reqs),
            "bold missing",
        )
        # The monospace run must carry weight 700: Docs treats weightedFontFamily.weight
        # as the source of truth for boldness, so the default 400 would render the
        # codespan monospace-but-NOT-bold and clobber the parent strong (3d render finding).
        bold_mono = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily") == "Courier New"
            and r["updateTextStyle"]["textStyle"]["weightedFontFamily"].get("weight") == 700
        ]
        self.assertGreaterEqual(len(bold_mono), 1, "codespan inside bold must carry weight 700")

    def test_plain_codespan_is_not_forced_bold(self):
        """A codespan NOT inside bold must not carry weight 700 (stays normal)."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "some `code` here")

        all_reqs = self._collect_all_requests(mock_api)
        mono = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily") == "Courier New"
        ]
        self.assertGreaterEqual(len(mono), 1)
        self.assertNotEqual(
            mono[0]["updateTextStyle"]["textStyle"]["weightedFontFamily"].get("weight"), 700,
            "plain codespan must not be forced to bold weight",
        )

    def test_table_cell_link_codespan_survives(self):
        """#182: a [`code`](url) link inside a table cell applies BOTH link and
        monospace font — the table path calls the same _walk_inlines."""
        from markdown_render import _insert_markdown

        table_md = "| H1 | H2 |\n|---|---|\n| [`code`](https://example.com) | plain |"

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_2x2_doc_response(),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)
        link_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("link", {}).get("url") == "https://example.com"
        ]
        font_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily") == "Courier New"
        ]
        self.assertGreaterEqual(len(link_reqs), 1, "table-cell link styling missing")
        self.assertGreaterEqual(len(font_reqs), 1, "table-cell codespan font missing inside link")

    def test_italic_emits_italic_text_style(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "some *emph* word")

        all_reqs = self._collect_all_requests(mock_api)
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        italic_reqs = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("italic") is True
        ]
        self.assertGreaterEqual(len(italic_reqs), 1)

    def test_existing_bold_still_works(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "**bold**")

        all_reqs = self._collect_all_requests(mock_api)
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        bold_reqs = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("bold") is True
        ]
        self.assertGreaterEqual(len(bold_reqs), 1)

    def test_existing_headings_still_work(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "## h2")

        all_reqs = self._collect_all_requests(mock_api)
        para_style_reqs = [r for r in all_reqs if "updateParagraphStyle" in r]
        h2_reqs = [
            r for r in para_style_reqs
            if r["updateParagraphStyle"].get("paragraphStyle", {}).get("namedStyleType") == "HEADING_2"
        ]
        self.assertGreaterEqual(len(h2_reqs), 1)

    def test_horizontal_rule_renders_as_unicode_line(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "---")

        all_reqs = self._collect_all_requests(mock_api)
        insert_reqs = [r for r in all_reqs if "insertText" in r]
        combined = "".join(r["insertText"]["text"] for r in insert_reqs)
        self.assertIn("─", combined)  # Box-drawing horizontal line

    def test_batch_chunking_preserved(self):
        from markdown_render import _insert_markdown

        # 105 separate paragraphs (blank line between each).
        # Each paragraph emits 3 requests: insertText + updateParagraphStyle
        # (NORMAL_TEXT + house rhythm) + deleteParagraphBullets (#301). The 104
        # blank markdown lines are preserved as empty paragraphs (#1768), 3 requests
        # each: (105 + 104) × 3 = 627 requests → batches of 50×12, then 27.
        # Single newline produces softbreak inside one paragraph;
        # double newline creates separate paragraph tokens.
        content = "\n\n".join(f"paragraph {i}" for i in range(105))
        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", content)

        call_sizes = [len(call[0][2]["requests"]) for call in mock_api.call_args_list]
        self.assertEqual(call_sizes, [50] * 12 + [27])

    def test_table_basic(self):
        """Tables emit insertTable batchUpdate request (real Docs table, not pipe text)."""
        from markdown_render import _insert_markdown

        # Simulate the two-phase table insertion:
        # Phase 1: insertTable request returns a reply with insertTable info.
        # Phase 2: documents.get returns doc with table cells having known indices.
        # Phase 3: cell inserts (reverse order).
        table_md = "| H1 | H2 |\n|---|---|\n| r1c1 | r1c2 |\n| r2c1 | r2c2 |"

        # documents.get response with 2 rows x 2 cols table cell structure
        # Each cell has a paragraph; indices must be discovered from the response.
        doc_with_table = {
            "body": {
                "content": [
                    {
                        "table": {
                            "rows": 2,
                            "columns": 2,
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 2, "endIndex": 3}], "startIndex": 2, "endIndex": 4},
                                        {"content": [{"paragraph": {}, "startIndex": 5, "endIndex": 6}], "startIndex": 5, "endIndex": 7},
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 9, "endIndex": 10}], "startIndex": 9, "endIndex": 11},
                                        {"content": [{"paragraph": {}, "startIndex": 12, "endIndex": 13}], "startIndex": 12, "endIndex": 14},
                                    ]
                                },
                            ]
                        },
                        "startIndex": 1,
                        "endIndex": 15,
                    }
                ]
            }
        }

        with patch("auth.api") as mock_api:
            # Phase 1: insertTable batchUpdate
            # Phase 2: documents.get to discover cell indices
            # Phase 3+: cell-text batchUpdates
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},  # insertTable batch
                doc_with_table,                       # documents.get
                {"replies": []},                      # cell text inserts (batch 1)
            ]
            _insert_markdown("doc1", table_md)

        # Verify an insertTable request was emitted (not just insertText of pipe chars)
        all_calls = mock_api.call_args_list
        all_bodies = [call[0][2] for call in all_calls if len(call[0]) > 2]
        insert_table_reqs = []
        for body in all_bodies:
            for req in body.get("requests", []):
                if "insertTable" in req:
                    insert_table_reqs.append(req)

        self.assertGreaterEqual(len(insert_table_reqs), 1, "Expected insertTable request in batchUpdate calls")

        # Verify rows and columns
        it = insert_table_reqs[0]["insertTable"]
        self.assertEqual(it["rows"], 3, "Table should have 3 rows: 1 header + 2 data")
        self.assertEqual(it["columns"], 2, "Table should have 2 columns")

        # Verify no pipe-separated plain text was inserted
        all_insert_text_reqs = []
        for body in all_bodies:
            for req in body.get("requests", []):
                if "insertText" in req:
                    all_insert_text_reqs.append(req)
        combined_text = "".join(r["insertText"]["text"] for r in all_insert_text_reqs)
        # Should NOT be a single big pipe-separated block (no "| H1 | H2 |" line)
        self.assertNotIn("| H1 | H2 |", combined_text, "Should not emit plain-text pipe table")

    # --- #145 additional table behaviors -------------------------------------

    def _all_table_requests(self, mock_api):
        """Flatten request bodies across api() calls, skipping GETs (no body)."""
        all_requests = []
        for call in mock_api.call_args_list:
            if len(call[0]) <= 2:
                continue  # GET (method, url) — no body
            body = call[0][2]
            all_requests.extend(body.get("requests", []))
        return all_requests

    def _table_2x2_doc_response(self):
        """Mock documents.get response with a single 2-row x 2-col table.

        Cell paragraph startIndex values are arranged so reverse-order inserts
        keep prior indices valid.
        """
        return {
            "body": {
                "content": [
                    {
                        "table": {
                            "rows": 2,
                            "columns": 2,
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 2, "endIndex": 3}], "startIndex": 2, "endIndex": 4},
                                        {"content": [{"paragraph": {}, "startIndex": 5, "endIndex": 6}], "startIndex": 5, "endIndex": 7},
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 9, "endIndex": 10}], "startIndex": 9, "endIndex": 11},
                                        {"content": [{"paragraph": {}, "startIndex": 12, "endIndex": 13}], "startIndex": 12, "endIndex": 14},
                                    ]
                                },
                            ],
                        },
                        "startIndex": 1,
                        "endIndex": 15,
                    }
                ]
            }
        }

    def test_table_header_row_is_bolded(self):
        """Header-row cells receive updateTextStyle with textStyle.bold=true."""
        from markdown_render import _insert_markdown

        table_md = "| H1 | H2 |\n|---|---|\n| r1c1 | r1c2 |\n| r2c1 | r2c2 |"

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_2x2_doc_response(),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)
        bold_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("bold") is True
        ]
        # Two header cells -> at least two bold style ranges covering them.
        self.assertGreaterEqual(
            len(bold_reqs), 2,
            f"Expected >=2 header-cell bold ranges; got {len(bold_reqs)}: {bold_reqs}",
        )
        # Bold ranges must cover header cells (startIndex 2 and 5).
        bold_starts = {r["updateTextStyle"]["range"]["startIndex"] for r in bold_reqs}
        self.assertIn(2, bold_starts, "Header cell H1 (startIndex=2) must be bolded")
        self.assertIn(5, bold_starts, "Header cell H2 (startIndex=5) must be bolded")
        # 'bold' must be in fields mask so the API honors it.
        for r in bold_reqs:
            fields = r["updateTextStyle"].get("fields", "")
            self.assertIn("bold", fields, f"updateTextStyle missing 'bold' in fields: {r}")

    def test_table_cells_populated_with_text(self):
        """Every markdown cell's text is inserted at its discovered cell index."""
        from markdown_render import _insert_markdown

        table_md = "| H1 | H2 |\n|---|---|\n| r1c1 | r1c2 |\n| r2c1 | r2c2 |"

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_2x2_doc_response(),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)
        insert_text_by_index = {
            r["insertText"]["location"]["index"]: r["insertText"]["text"]
            for r in all_reqs if "insertText" in r
        }
        # Each cell startIndex from the mock should map to the matching markdown text.
        expected = {2: "H1", 5: "H2", 9: "r1c1", 12: "r1c2"}
        for idx, text in expected.items():
            self.assertEqual(
                insert_text_by_index.get(idx), text,
                f"Cell at index {idx} expected text {text!r}; got {insert_text_by_index.get(idx)!r}",
            )

    def _nested_subtab_table_doc_response(self, tab_id="t.child"):
        """documents.get read-back with the 2x2 table nested inside a depth-1 sub-tab.

        The table lives under ``tabs[0].childTabs[0].documentTab`` (tabId ``t.child``),
        with the parent tab (``t.parent``) carrying only a trailing paragraph. A flat
        scan of top-level ``tabs`` — the #198 bug — never recurses into ``childTabs``,
        so it finds the parent but not the child and returns no table element.
        """
        table_elem = self._table_2x2_doc_response()["body"]["content"][0]
        return {
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.parent", "title": "Parent Tab"},
                    "documentTab": {"body": {"content": [{"startIndex": 0, "endIndex": 1}]}},
                    "childTabs": [
                        {
                            "tabProperties": {
                                "tabId": tab_id,
                                "title": "Child Tab",
                                "parentTabId": "t.parent",
                            },
                            "documentTab": {"body": {"content": [table_elem]}},
                        }
                    ],
                }
            ]
        }

    def _tab_end_doc_response(self, tab_id="t.child", end_index=7):
        """Minimal tab response whose trailing paragraph ends at end_index."""
        return {
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.parent", "title": "Parent Tab"},
                    "documentTab": {"body": {"content": [{"startIndex": 0, "endIndex": 1}]}},
                    "childTabs": [
                        {
                            "tabProperties": {
                                "tabId": tab_id,
                                "title": "Child Tab",
                                "parentTabId": "t.parent",
                            },
                            "documentTab": {
                                "body": {
                                    "content": [
                                        {"startIndex": 0, "endIndex": 1},
                                        {"paragraph": {}, "startIndex": end_index - 1, "endIndex": end_index},
                                    ]
                                }
                            },
                        }
                    ],
                }
            ]
        }

    def test_table_cells_populated_in_nested_subtab(self):
        """#198: a markdown table written to a nested sub-tab fills its cells.

        Regression for silent data loss: ``_get_body_content`` flat-scanned only the
        top-level ``tabs`` list, so for a depth>=1 (sub-)tab the read-back returned [],
        no table element matched, the cell-fill loop skipped every cell, and Phase 1's
        ``insertTable`` left an empty grid. Top-level tabs rendered fine, which is why
        the failure was silent and table-specific.
        """
        from markdown_render import _insert_markdown

        table_md = "| H1 | H2 |\n|---|---|\n| r1c1 | r1c2 |\n| r2c1 | r2c2 |"

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._nested_subtab_table_doc_response("t.child"),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md, tab_id="t.child")

        all_reqs = self._all_table_requests(mock_api)
        insert_text_by_index = {
            r["insertText"]["location"]["index"]: r["insertText"]["text"]
            for r in all_reqs if "insertText" in r
        }
        # Same cell indices as the top-level case — the nested lookup must find the
        # identical table body and fill all four cells.
        expected = {2: "H1", 5: "H2", 9: "r1c1", 12: "r1c2"}
        for idx, text in expected.items():
            self.assertEqual(
                insert_text_by_index.get(idx), text,
                f"Nested-subtab cell at index {idx} expected {text!r}; "
                f"got {insert_text_by_index.get(idx)!r}",
            )

    def test_table_after_prior_tab_content_inserts_before_segment_end(self):
        """Live Docs rejects insertTable at the tab segment end; append at endIndex - 1."""
        from markdown_render import _insert_markdown

        table_md = "Intro\n\n| H1 | H2 |\n|---|---|\n| r1c1 | r1c2 |"
        insert_table_locations = []

        def fake_api(method, url, data=None):
            if method == "GET":
                # Only the fixed path asks for the live tab end before insertTable.
                if not insert_table_locations:
                    return self._tab_end_doc_response("t.child", end_index=7)
                return self._nested_subtab_table_doc_response("t.child")
            if data:
                for req in data.get("requests", []):
                    if "insertTable" in req:
                        insert_table_locations.append(req["insertTable"]["location"])
            return {"replies": []}

        with patch("auth.api", side_effect=fake_api):
            _insert_markdown("doc1", table_md, tab_id="t.child")

        self.assertEqual(len(insert_table_locations), 1)
        self.assertEqual(
            insert_table_locations[0]["index"],
            6,
            "insertTable must use the valid append index endIndex - 1, not the rejected segment endIndex",
        )

    def test_image_after_table_in_tab_inserts_before_segment_end(self):
        """Markdown image insertion after a flushed table must also clamp to endIndex - 1."""
        from markdown_render import _insert_markdown

        content = "Intro\n\n| H1 | H2 |\n|---|---|\n| r1c1 | r1c2 |\n\n![Diagram](https://example.com/diagram.png)"
        # The blank markdown line after the table is preserved as an empty paragraph
        # (#1768 house style), so it takes the clamped append index endIndex - 1 = 15
        # and the image lands one unit later at 16.
        insert_table_seen = False
        cell_fill_seen = False
        image_locations = []

        def fake_api(method, url, data=None):
            nonlocal insert_table_seen, cell_fill_seen
            if method == "GET":
                if not insert_table_seen:
                    return self._tab_end_doc_response("t.child", end_index=7)
                if not cell_fill_seen:
                    return self._nested_subtab_table_doc_response("t.child")
                return self._tab_end_doc_response("t.child", end_index=16)
            if data:
                requests = data.get("requests", [])
                for req in requests:
                    if "insertTable" in req:
                        insert_table_seen = True
                    elif "insertInlineImage" in req:
                        image_locations.append(req["insertInlineImage"]["location"])
                if any("insertText" in req and req["insertText"].get("text") in {"H1", "H2", "r1c1", "r1c2"} for req in requests):
                    cell_fill_seen = True
            return {"replies": []}

        with patch("auth.api", side_effect=fake_api):
            _insert_markdown("doc1", content, tab_id="t.child")

        self.assertEqual(len(image_locations), 1)
        self.assertEqual(
            image_locations[0]["index"],
            16,
            "insertInlineImage must follow the blank paragraph placed at endIndex - 1",
        )

    def test_table_emits_no_pipe_characters_anywhere(self):
        """No insertText.text across the whole conversion contains a raw '|'."""
        from markdown_render import _insert_markdown

        table_md = "| Col A | Col B |\n|---|---|\n| alpha | bravo |\n| gamma | delta |"

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_2x2_doc_response(),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)
        for r in all_reqs:
            if "insertText" in r:
                text = r["insertText"]["text"]
                self.assertNotIn(
                    "|", text,
                    f"Raw pipe character leaked into insertText: {text!r}",
                )

    def test_table_targets_just_inserted_table_when_body_has_prior_table(self):
        """When a doc body contains a pre-existing table, cell inserts go into the new one.

        Reproduces the 'first-found-table' bug: iterating body_content top-down
        and break-on-first-table would write the new markdown's cells into the
        wrong (pre-existing) table when insertion happens past index 1.
        """
        from markdown_render import _insert_markdown

        table_md = "| H1 | H2 |\n|---|---|\n| r1c1 | r1c2 |"

        # documents.get returns two tables: a pre-existing one near the doc
        # start (cells at low indices) and the just-inserted one at index 50+
        # (cells at high indices). The fix must pick the latter.
        doc_with_two_tables = {
            "body": {
                "content": [
                    {  # Pre-existing table near doc start.
                        "table": {
                            "rows": 1,
                            "columns": 2,
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 2, "endIndex": 3}], "startIndex": 2, "endIndex": 4},
                                        {"content": [{"paragraph": {}, "startIndex": 5, "endIndex": 6}], "startIndex": 5, "endIndex": 7},
                                    ]
                                },
                            ],
                        },
                        "startIndex": 1,
                        "endIndex": 10,
                    },
                    {  # Newly-inserted table further down.
                        "table": {
                            "rows": 2,
                            "columns": 2,
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 51, "endIndex": 52}], "startIndex": 51, "endIndex": 53},
                                        {"content": [{"paragraph": {}, "startIndex": 54, "endIndex": 55}], "startIndex": 54, "endIndex": 56},
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 58, "endIndex": 59}], "startIndex": 58, "endIndex": 60},
                                        {"content": [{"paragraph": {}, "startIndex": 61, "endIndex": 62}], "startIndex": 61, "endIndex": 63},
                                    ]
                                },
                            ],
                        },
                        "startIndex": 50,
                        "endIndex": 64,
                    },
                ]
            }
        }

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                doc_with_two_tables,
                {"replies": []},
            ]
            # Insert at index=50 — the location of the new table.
            _insert_markdown("doc1", table_md, index=50)

        all_reqs = self._all_table_requests(mock_api)
        cell_text_indices = [
            r["insertText"]["location"]["index"]
            for r in all_reqs if "insertText" in r
        ]
        # All cell text inserts must land inside the newly-inserted table
        # (indices in [50, 64)), NOT inside the pre-existing one ([1, 10)).
        self.assertTrue(
            all(50 <= i < 64 for i in cell_text_indices),
            f"Cell inserts targeted wrong table; indices were {cell_text_indices}",
        )
        self.assertFalse(
            any(1 <= i < 10 for i in cell_text_indices),
            f"Cell inserts leaked into pre-existing table; indices were {cell_text_indices}",
        )

    def test_content_after_table_lands_past_filled_cells(self):
        """Paragraph following a table inserts AFTER the filled table, not inside a cell.

        Repro of a real bug surfaced by live-doc validation: after the table is
        inserted and cells are filled, the stale endIndex from documents.get
        (captured BEFORE cell text was inserted) was used to advance
        current_index. Subsequent content then landed inside the last cell
        because cell-fill chars had pushed the table's true end further out.
        """
        from markdown_render import _insert_markdown

        # 2-row mock-compatible table: header "H1"/"H2" (4 chars) + body
        # "ab"/"cd" (4 chars) = 8 chars inserted into a table whose pre-fill
        # endIndex in the mock is 15. Trailing paragraph must land at >=
        # 15 + 8 = 23.
        content = (
            "| H1 | H2 |\n"
            "|---|---|\n"
            "| ab | cd |\n"
            "\n"
            "after-table-paragraph"
        )

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_2x2_doc_response(),  # pre-fill endIndex = 15
                {"replies": []},                  # cell-text+bold batch
                {"replies": []},                  # trailing-paragraph batch
            ]
            _insert_markdown("doc1", content)

        all_reqs = self._all_table_requests(mock_api)
        # Find the insertText for the trailing paragraph.
        trailing = [
            r for r in all_reqs
            if "insertText" in r
            and "after-table-paragraph" in r["insertText"]["text"]
        ]
        self.assertEqual(len(trailing), 1, f"Expected one trailing-paragraph insertText; got {trailing}")
        trailing_index = trailing[0]["insertText"]["location"]["index"]
        # Must land at or past the post-fill end of the table (15 pre-fill +
        # 8 cell chars = 23). Anything < 23 means it leaked into a cell.
        self.assertGreaterEqual(
            trailing_index, 23,
            f"Trailing content landed inside table; index={trailing_index} (need >=23)",
        )

    def test_tab_id_propagated_to_all_requests(self):
        from markdown_render import _insert_markdown

        content = "# Heading\n\n**bold** *italic*\n\n- item1\n- item2"
        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", content, tab_id="t.xyz")

        all_reqs = self._collect_all_requests(mock_api)
        for req in all_reqs:
            if "insertText" in req:
                loc = req["insertText"]["location"]
                self.assertEqual(loc.get("tabId"), "t.xyz", f"insertText missing tabId: {req}")
            elif "updateTextStyle" in req:
                rng = req["updateTextStyle"]["range"]
                self.assertEqual(rng.get("tabId"), "t.xyz", f"updateTextStyle missing tabId: {req}")
            elif "updateParagraphStyle" in req:
                rng = req["updateParagraphStyle"]["range"]
                self.assertEqual(rng.get("tabId"), "t.xyz", f"updateParagraphStyle missing tabId: {req}")
            elif "createParagraphBullets" in req:
                rng = req["createParagraphBullets"]["range"]
                self.assertEqual(rng.get("tabId"), "t.xyz", f"createParagraphBullets missing tabId: {req}")


class TestListItemContentLoss(unittest.TestCase):
    """Regression (#528): list items silently lost content.

    All three symptoms were silent — the write "succeeded" and the doc looked
    plausible, so only an assertion on the emitted requests catches a relapse:
      1. an inline image in a list item was dropped (image tokens flatten to "",
         and an image-only item flattened to "" lost its whole line);
      2. a loose (multi-paragraph) item kept only its first paragraph;
      3. an empty item emitted nothing, renumbering every following item.
    """

    def _collect(self, mock_api):
        all_requests = []
        for call in mock_api.call_args_list:
            if len(call[0]) <= 2:
                continue  # GET, no body
            all_requests.extend(call[0][2].get("requests", []))
        return all_requests

    def _render(self, content, **kwargs):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", content, **kwargs)
        return self._collect(mock_api)

    def test_image_only_list_item_emits_inline_image(self):
        all_reqs = self._render("- ![alt](https://x/img.png)\n- plain\n")

        images = [r["insertInlineImage"] for r in all_reqs if "insertInlineImage" in r]
        self.assertEqual(
            len(images), 1,
            "inline image in a list item must be inserted, not flattened away",
        )
        self.assertEqual(images[0]["uri"], "https://x/img.png")
        # The image occupies index 1 and the item's newline index 2, so the
        # following item starts at 3 — the image is a real character, and the
        # bullet range must cover both items.
        self.assertEqual(images[0]["location"]["index"], 1)
        plain = [r["insertText"] for r in all_reqs
                 if "insertText" in r and r["insertText"]["text"] == "plain\n"]
        self.assertEqual(len(plain), 1)
        self.assertEqual(plain[0]["location"]["index"], 3)
        bullet_rng = [r["createParagraphBullets"]["range"] for r in all_reqs
                      if "createParagraphBullets" in r][0]
        self.assertEqual((bullet_rng["startIndex"], bullet_rng["endIndex"]), (1, 9))

    def test_image_between_text_in_list_item_keeps_text_and_styles(self):
        all_reqs = self._render("- see ![alt](https://x/img.png) **here**\n")

        inserts = [(r["insertText"]["location"]["index"], r["insertText"]["text"])
                   for r in all_reqs if "insertText" in r]
        self.assertEqual(inserts, [(1, "see "), (6, " here"), (11, "\n")])
        images = [r["insertInlineImage"] for r in all_reqs if "insertInlineImage" in r]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]["location"]["index"], 5)
        # Inline styling offsets must be measured past the image, which occupies
        # one index: "here" starts at 7 (1 + "see " + image) and runs 4 chars.
        bold = [r["updateTextStyle"]["range"] for r in all_reqs
                if "updateTextStyle" in r
                and r["updateTextStyle"]["textStyle"].get("bold")]
        self.assertEqual(len(bold), 1)
        self.assertEqual((bold[0]["startIndex"], bold[0]["endIndex"]), (7, 11))

    def test_nested_image_list_item_keeps_tab_prefix_before_image(self):
        """The nesting tab must still lead the line when the item opens with an
        image — otherwise the item loses its bullet level (and #298's tab
        accounting) on the segmented path."""
        all_reqs = self._render("- top\n  - ![alt](https://x/img.png)\n")

        inserts = [(r["insertText"]["location"]["index"], r["insertText"]["text"])
                   for r in all_reqs if "insertText" in r]
        self.assertIn((5, "\t"), inserts, f"nested image item lost its tab: {inserts}")
        images = [r["insertInlineImage"] for r in all_reqs if "insertInlineImage" in r]
        self.assertEqual(images[0]["location"]["index"], 6)
        # One tab consumed by createParagraphBullets: pre-consumption end 8.
        # The per-line NORMAL_TEXT resets run before bullets (#2001), so they are
        # pre-consumption: "top\n" [1,5) and the image line "\t<img>\n" [5,8).
        bullet_rng = [r["createParagraphBullets"]["range"] for r in all_reqs
                      if "createParagraphBullets" in r][0]
        self.assertEqual(bullet_rng["endIndex"], 8)
        normal_rngs = [(r["updateParagraphStyle"]["range"]["startIndex"],
                        r["updateParagraphStyle"]["range"]["endIndex"]) for r in all_reqs
                       if "updateParagraphStyle" in r
                       and r["updateParagraphStyle"]["paragraphStyle"].get("namedStyleType")
                       == "NORMAL_TEXT"]
        self.assertEqual(normal_rngs, [(1, 5), (5, 8)])

    def test_loose_list_item_keeps_every_paragraph(self):
        all_reqs = self._render("- first para\n\n  second para\n- other\n")

        inserts = [(r["insertText"]["location"]["index"], r["insertText"]["text"])
                   for r in all_reqs if "insertText" in r]
        self.assertEqual(
            inserts,
            [(1, "first para\n"), (12, "second para\n"), (24, "other\n")],
            "the 2nd paragraph of a loose list item must survive",
        )

    def test_loose_continuation_is_unbulleted_and_indented(self):
        """The continuation paragraph is inserted as an ordinary list line so its
        text survives, then un-bulleted and indented to the item's text column —
        leaving the bullet on would split one item into two (and renumber an
        ordered list). Both fix-ups must run AFTER createParagraphBullets."""
        all_reqs = self._render("1. first para\n\n   second para\n2. other\n")

        kinds = [next(iter(r)) for r in all_reqs]
        self.assertIn("deleteParagraphBullets", kinds)
        self.assertLess(
            kinds.index("createParagraphBullets"), kinds.index("deleteParagraphBullets"),
            "un-bulleting the continuation must follow createParagraphBullets",
        )
        unbullet = [r["deleteParagraphBullets"]["range"] for r in all_reqs
                    if "deleteParagraphBullets" in r]
        self.assertEqual(len(unbullet), 1)
        self.assertEqual((unbullet[0]["startIndex"], unbullet[0]["endIndex"]), (12, 24))
        indent = [r["updateParagraphStyle"] for r in all_reqs
                  if "updateParagraphStyle" in r
                  and "indentStart" in r["updateParagraphStyle"]["paragraphStyle"]]
        self.assertEqual(len(indent), 1)
        self.assertEqual(indent[0]["range"], unbullet[0])
        self.assertEqual(
            indent[0]["paragraphStyle"]["indentStart"],
            {"magnitude": config.LIST_INDENT_PER_LEVEL_PT, "unit": "PT"},
        )
        self.assertEqual(indent[0]["fields"], "indentStart,indentFirstLine")

    def test_loose_continuation_ranges_are_post_tab_consumption(self):
        """A continuation paragraph's fix-up ranges run after
        createParagraphBullets has deleted the nesting tabs, so they must use
        post-consumption indexes — the #298 trap, now reachable one level down."""
        all_reqs = self._render("- a\n  - n1\n\n    n2\n- b\n\n  b2\n")

        # Pre-consumption: "a\n"(1-3) "\tn1\n"(3-7) "\tn2\n"(7-11) "b\n"(11-13)
        # "b2\n"(13-16); 2 tabs consumed -> "n2\n" lands at 6-9, "b2\n" at 11-14.
        unbullet = [(r["deleteParagraphBullets"]["range"]["startIndex"],
                     r["deleteParagraphBullets"]["range"]["endIndex"])
                    for r in all_reqs if "deleteParagraphBullets" in r]
        self.assertEqual(unbullet, [(6, 9), (11, 14)])
        # The nested continuation indents one level deeper than the top-level one.
        magnitudes = [r["updateParagraphStyle"]["paragraphStyle"]["indentStart"]["magnitude"]
                      for r in all_reqs
                      if "updateParagraphStyle" in r
                      and "indentStart" in r["updateParagraphStyle"]["paragraphStyle"]]
        self.assertEqual(
            magnitudes,
            [2 * config.LIST_INDENT_PER_LEVEL_PT, config.LIST_INDENT_PER_LEVEL_PT],
        )

    def test_empty_list_item_still_emits_a_line(self):
        """An item with no text emitted nothing at all, so the bullet vanished and
        every following item of an ordered list shifted up by one number."""
        all_reqs = self._render("1. one\n2.\n3. three\n")

        inserts = [(r["insertText"]["location"]["index"], r["insertText"]["text"])
                   for r in all_reqs if "insertText" in r]
        self.assertEqual(inserts, [(1, "one\n"), (5, "\n"), (6, "three\n")])
        bullet_rng = [r["createParagraphBullets"]["range"] for r in all_reqs
                      if "createParagraphBullets" in r][0]
        self.assertEqual(
            (bullet_rng["startIndex"], bullet_rng["endIndex"]), (1, 12),
            "the empty item's line must be inside the bulleted range",
        )

    def test_list_item_content_carries_tab_id(self):
        """Every request on the new list paths must be tab-scoped, or the write
        lands in the document body instead of the tab."""
        all_reqs = self._render(
            "- ![alt](https://x/img.png)\n- loose\n\n  more\n", tab_id="t.abc"
        )

        self.assertTrue(any("insertInlineImage" in r for r in all_reqs))
        self.assertTrue(any("deleteParagraphBullets" in r for r in all_reqs))
        for req in all_reqs:
            payload = next(iter(req.values()))
            scope = payload.get("location") or payload.get("range") or {}
            self.assertEqual(scope.get("tabId"), "t.abc", f"missing tabId: {req}")


class TestTableCellInlineFormatting(unittest.TestCase):
    """#159: Inline markdown constructs inside table cells emit updateTextStyle requests."""

    def _all_table_requests(self, mock_api):
        """Flatten request bodies across api() calls, skipping GETs (no body)."""
        all_requests = []
        for call in mock_api.call_args_list:
            if len(call[0]) <= 2:
                continue  # GET (method, url) — no body
            body = call[0][2]
            all_requests.extend(body.get("requests", []))
        return all_requests

    def _table_3row_doc_response(self):
        """Mock documents.get with a 3-row x 2-col table.

        Row 0: header cells at startIndex 2 (col0), 5 (col1)
        Row 1: body cells at startIndex 9 (col0), 12 (col1)
        Row 2: body cells at startIndex 16 (col0), 20 (col1)
        """
        return {
            "body": {
                "content": [
                    {
                        "table": {
                            "rows": 3,
                            "columns": 2,
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 2, "endIndex": 3}], "startIndex": 2, "endIndex": 4},
                                        {"content": [{"paragraph": {}, "startIndex": 5, "endIndex": 6}], "startIndex": 5, "endIndex": 7},
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 9, "endIndex": 10}], "startIndex": 9, "endIndex": 11},
                                        {"content": [{"paragraph": {}, "startIndex": 12, "endIndex": 13}], "startIndex": 12, "endIndex": 14},
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 16, "endIndex": 17}], "startIndex": 16, "endIndex": 18},
                                        {"content": [{"paragraph": {}, "startIndex": 20, "endIndex": 21}], "startIndex": 20, "endIndex": 22},
                                    ]
                                },
                            ],
                        },
                        "startIndex": 1,
                        "endIndex": 25,
                    }
                ]
            }
        }

    def test_cell_bold_targets_only_the_bold_substring(self):
        """**bold** in a body cell emits updateTextStyle.bold=true targeting only that substring.

        Cell text is "see **bold** here" — the bold substring "bold" starts at
        offset 4 from the cell_start.  The style range must be
        [cell_start + 4, cell_start + 8], NOT [cell_start, cell_start + len(whole text)].
        """
        from markdown_render import _insert_markdown

        # Header row plain, body row 1 has bold in col0
        table_md = (
            "| H1 | H2 |\n"
            "|---|---|\n"
            "| see **bold** here | plain |\n"
            "| other | cell |\n"
        )

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_3row_doc_response(),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)
        bold_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("bold") is True
        ]
        # The body cell (col0 of row 1) has startIndex=9.
        # "see " is 4 chars, "bold" is 4 chars → range [9+4, 9+8] = [13, 17].
        body_cell_bold = [
            r for r in bold_reqs
            if r["updateTextStyle"]["range"]["startIndex"] == 13
        ]
        self.assertEqual(
            len(body_cell_bold), 1,
            f"Expected exactly one bold style at startIndex=13 (substring offset); "
            f"bold_reqs={bold_reqs}",
        )
        self.assertEqual(
            body_cell_bold[0]["updateTextStyle"]["range"]["endIndex"], 17,
            "Bold range endIndex should be cell_start+8 (covers only 'bold')",
        )
        self.assertIn(
            "bold",
            body_cell_bold[0]["updateTextStyle"].get("fields", ""),
            "fields mask must include 'bold'",
        )

    def test_cell_italic_targets_only_the_italic_substring(self):
        """*italic* in a body cell emits updateTextStyle.italic targeting only that substring."""
        from markdown_render import _insert_markdown

        table_md = (
            "| H1 | H2 |\n"
            "|---|---|\n"
            "| x *italic* y | plain |\n"
            "| other | cell |\n"
        )

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_3row_doc_response(),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)
        italic_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("italic") is True
        ]
        # Row 1, col 0 → cell_start=9.  Text "x italic y" (no asterisks).
        # "x " is 2 chars, "italic" is 6 chars → range [9+2, 9+8] = [11, 17].
        body_cell_italic = [
            r for r in italic_reqs
            if r["updateTextStyle"]["range"]["startIndex"] == 11
        ]
        self.assertEqual(
            len(body_cell_italic), 1,
            f"Expected italic style at startIndex=11 (substring offset); "
            f"italic_reqs={italic_reqs}",
        )
        self.assertEqual(
            body_cell_italic[0]["updateTextStyle"]["range"]["endIndex"], 17,
            "Italic range endIndex should be cell_start+8 (covers only 'italic')",
        )
        self.assertIn(
            "italic",
            body_cell_italic[0]["updateTextStyle"].get("fields", ""),
            "fields mask must include 'italic'",
        )

    def test_cell_inline_code_targets_only_the_code_substring(self):
        """`code` in a body cell emits Courier New styling on just the code substring."""
        from markdown_render import _insert_markdown

        table_md = (
            "| H1 | H2 |\n"
            "|---|---|\n"
            "| run `foo` now | plain |\n"
            "| other | cell |\n"
        )

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_3row_doc_response(),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)
        code_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily") == "Courier New"
        ]
        # Row 1, col 0 → cell_start=9.  Text "run foo now".
        # "run " is 4 chars, "foo" is 3 chars → range [9+4, 9+7] = [13, 16].
        body_cell_code = [
            r for r in code_reqs
            if r["updateTextStyle"]["range"]["startIndex"] == 13
        ]
        self.assertEqual(
            len(body_cell_code), 1,
            f"Expected Courier New style at startIndex=13 (substring offset); "
            f"code_reqs={code_reqs}",
        )
        self.assertEqual(
            body_cell_code[0]["updateTextStyle"]["range"]["endIndex"], 16,
            "Code range endIndex should be cell_start+7 (covers only 'foo')",
        )
        self.assertIn(
            "weightedFontFamily",
            body_cell_code[0]["updateTextStyle"].get("fields", ""),
            "fields mask must include 'weightedFontFamily'",
        )

    def test_cell_link_targets_only_the_link_substring(self):
        """[text](url) in a body cell emits link styling on just the link text substring."""
        from markdown_render import _insert_markdown

        table_md = (
            "| H1 | H2 |\n"
            "|---|---|\n"
            "| see [docs](https://example.com) here | plain |\n"
            "| other | cell |\n"
        )

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                self._table_3row_doc_response(),
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)
        link_reqs = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("link", {}).get("url") == "https://example.com"
        ]
        # Row 1, col 0 → cell_start=9.  Text "see docs here".
        # "see " is 4 chars, "docs" is 4 chars → range [9+4, 9+8] = [13, 17].
        body_cell_link = [
            r for r in link_reqs
            if r["updateTextStyle"]["range"]["startIndex"] == 13
        ]
        self.assertEqual(
            len(body_cell_link), 1,
            f"Expected link style at startIndex=13; link_reqs={link_reqs}",
        )
        self.assertEqual(
            body_cell_link[0]["updateTextStyle"]["range"]["endIndex"], 17,
            "Link range endIndex should be cell_start+8 (covers only 'docs')",
        )
        self.assertIn(
            "link",
            body_cell_link[0]["updateTextStyle"].get("fields", ""),
            "fields mask must include 'link'",
        )

    def test_header_cell_italic_composes_with_header_bold(self):
        """Header cell with *italic* emits BOTH header-bold AND italic updateTextStyle requests.

        The two requests must use separate fields masks ('bold' vs 'italic') so
        they compose rather than one overriding the other.
        """
        from markdown_render import _insert_markdown

        # Header row col 0 has plain italic text; col 1 is plain.
        table_md = (
            "| *title* | H2 |\n"
            "|---|---|\n"
            "| body1 | body2 |\n"
        )

        # Use the 2-row (header + 1 body) doc shape; reuse existing helper via inline def.
        doc_response = {
            "body": {
                "content": [
                    {
                        "table": {
                            "rows": 2,
                            "columns": 2,
                            "tableRows": [
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 2, "endIndex": 3}], "startIndex": 2, "endIndex": 4},
                                        {"content": [{"paragraph": {}, "startIndex": 5, "endIndex": 6}], "startIndex": 5, "endIndex": 7},
                                    ]
                                },
                                {
                                    "tableCells": [
                                        {"content": [{"paragraph": {}, "startIndex": 9, "endIndex": 10}], "startIndex": 9, "endIndex": 11},
                                        {"content": [{"paragraph": {}, "startIndex": 12, "endIndex": 13}], "startIndex": 12, "endIndex": 14},
                                    ]
                                },
                            ],
                        },
                        "startIndex": 1,
                        "endIndex": 16,
                    }
                ]
            }
        }

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [
                {"replies": [{"insertTable": {}}]},
                doc_response,
                {"replies": []},
            ]
            _insert_markdown("doc1", table_md)

        all_reqs = self._all_table_requests(mock_api)

        # The header cell (col 0) has cell_start=2 and plain text "title" (5 chars).
        # Header-bold must cover [2, 7] (bold=True, fields="bold").
        # Inline-italic must cover [2, 7] too (italic=True, fields="italic") since
        # the entire cell content is italic.

        bold_reqs_at_2 = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("bold") is True
            and r["updateTextStyle"]["range"]["startIndex"] == 2
        ]
        italic_reqs_at_2 = [
            r for r in all_reqs
            if "updateTextStyle" in r
            and r["updateTextStyle"].get("textStyle", {}).get("italic") is True
            and r["updateTextStyle"]["range"]["startIndex"] == 2
        ]

        self.assertGreaterEqual(
            len(bold_reqs_at_2), 1,
            f"Expected header-bold at startIndex=2; all updateTextStyle reqs: "
            f"{[r for r in all_reqs if 'updateTextStyle' in r]}",
        )
        self.assertGreaterEqual(
            len(italic_reqs_at_2), 1,
            f"Expected inline-italic at startIndex=2; all updateTextStyle reqs: "
            f"{[r for r in all_reqs if 'updateTextStyle' in r]}",
        )

        # The two requests must use different fields masks to compose properly.
        bold_fields = bold_reqs_at_2[0]["updateTextStyle"].get("fields", "")
        italic_fields = italic_reqs_at_2[0]["updateTextStyle"].get("fields", "")
        self.assertIn("bold", bold_fields, "Header-bold request must have 'bold' in fields")
        self.assertIn("italic", italic_fields, "Inline-italic request must have 'italic' in fields")
        # They must be separate requests (different textStyle content).
        self.assertNotEqual(
            bold_reqs_at_2[0], italic_reqs_at_2[0],
            "Header-bold and inline-italic must be two distinct requests",
        )


class TestParagraphNormalTextStyle(unittest.TestCase):
    """Gap 2a: paragraph branch emits namedStyleType NORMAL_TEXT to reset cascade."""

    def _collect_all_requests(self, mock_api):
        all_requests = []
        for call in mock_api.call_args_list:
            body = call[0][2]
            all_requests.extend(body.get("requests", []))
        return all_requests

    def test_paragraph_emits_normal_text_named_style(self):
        """Plain paragraph block emits updateParagraphStyle with NORMAL_TEXT."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "Hello world paragraph.")

        all_reqs = self._collect_all_requests(mock_api)
        para_style_reqs = [r for r in all_reqs if "updateParagraphStyle" in r]
        normal_text_reqs = [
            r for r in para_style_reqs
            if r["updateParagraphStyle"].get("paragraphStyle", {}).get("namedStyleType") == "NORMAL_TEXT"
        ]
        self.assertGreaterEqual(len(normal_text_reqs), 1,
                                "Plain paragraph should emit updateParagraphStyle with NORMAL_TEXT")

    def test_paragraph_normal_text_resets_between_heading_and_paragraph(self):
        """NORMAL_TEXT is emitted after a heading to reset any cascaded style."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "# Heading\n\nFollowing paragraph")

        all_reqs = self._collect_all_requests(mock_api)
        para_style_reqs = [r for r in all_reqs if "updateParagraphStyle" in r]
        style_types = [
            r["updateParagraphStyle"]["paragraphStyle"]["namedStyleType"]
            for r in para_style_reqs
        ]
        self.assertIn("HEADING_1", style_types)
        self.assertIn("NORMAL_TEXT", style_types)


class TestParagraphBulletClearAndSpacing(unittest.TestCase):
    """#301: headings/paragraphs must clear inherited bullets (bug 1) and carry
    inter-paragraph spacing (bug 2)."""

    def _collect_all_requests(self, mock_api):
        all_requests = []
        for call in mock_api.call_args_list:
            body = call[0][2]
            all_requests.extend(body.get("requests", []))
        return all_requests

    # --- Bug 1: deleteParagraphBullets clears inherited bullets ---------------

    def test_paragraph_emits_delete_paragraph_bullets(self):
        """A normal paragraph emits deleteParagraphBullets so it cannot inherit a
        bullet from the tab's anchor paragraph."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "Just a plain paragraph.")

        all_reqs = self._collect_all_requests(mock_api)
        del_reqs = [r for r in all_reqs if "deleteParagraphBullets" in r]
        self.assertEqual(len(del_reqs), 1,
                         "plain paragraph must emit exactly one deleteParagraphBullets")

    def test_heading_emits_delete_paragraph_bullets(self):
        """Headings inherit the anchor bullet too — they must clear it."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "# Title")

        all_reqs = self._collect_all_requests(mock_api)
        del_reqs = [r for r in all_reqs if "deleteParagraphBullets" in r]
        self.assertEqual(len(del_reqs), 1,
                         "heading must emit exactly one deleteParagraphBullets")

    def test_delete_paragraph_bullets_range_matches_paragraph_style_range(self):
        """The bullet-clear covers the same range as the paragraph's style request."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "Body text here.")

        all_reqs = self._collect_all_requests(mock_api)
        del_rng = [r["deleteParagraphBullets"]["range"] for r in all_reqs
                   if "deleteParagraphBullets" in r][0]
        style_rng = [r["updateParagraphStyle"]["range"] for r in all_reqs
                     if "updateParagraphStyle" in r
                     and r["updateParagraphStyle"]["paragraphStyle"].get("namedStyleType") == "NORMAL_TEXT"][0]
        self.assertEqual(del_rng, style_rng)

    def test_list_items_do_not_clear_their_own_bullets(self):
        """The list branch keeps bullets — no deleteParagraphBullets over the list
        range would undo createParagraphBullets."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "- one\n- two")

        all_reqs = self._collect_all_requests(mock_api)
        bullet_rng = [r["createParagraphBullets"]["range"] for r in all_reqs
                      if "createParagraphBullets" in r][0]
        clobbering = [
            r for r in all_reqs
            if "deleteParagraphBullets" in r
            and r["deleteParagraphBullets"]["range"] == bullet_rng
        ]
        self.assertEqual(clobbering, [],
                         "list bullets must not be cleared by deleteParagraphBullets")

    def test_rich_paragraph_with_image_emits_delete_paragraph_bullets(self):
        """The inline-image paragraph path also clears inherited bullets."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "text ![x](https://e.com/i.png) more")

        all_reqs = self._collect_all_requests(mock_api)
        del_reqs = [r for r in all_reqs if "deleteParagraphBullets" in r]
        self.assertEqual(len(del_reqs), 1)

    def test_bullet_clear_carries_tab_id_for_tab_writes(self):
        """When writing into a tab, the deleteParagraphBullets range must be
        tab-scoped or it targets the wrong segment."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "Paragraph in a tab.", tab_id="t.abc")

        all_reqs = self._collect_all_requests(mock_api)
        del_rng = [r["deleteParagraphBullets"]["range"] for r in all_reqs
                   if "deleteParagraphBullets" in r][0]
        self.assertEqual(del_rng.get("tabId"), "t.abc")

    # --- Bug 2: inter-paragraph spacing --------------------------------------

class TestCodeFont(unittest.TestCase):
    """#1768: code font is the house Courier New, not a caller-supplied parameter."""

    def _collect_all_requests(self, mock_api):
        all_requests = []
        for call in mock_api.call_args_list:
            body = call[0][2]
            all_requests.extend(body.get("requests", []))
        return all_requests

    def test_inline_code_default_is_courier_new(self):
        """Inline code is always Courier New."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "some `code` here")

        all_reqs = self._collect_all_requests(mock_api)
        style_reqs = [r for r in all_reqs if "updateTextStyle" in r]
        font_reqs = [
            r for r in style_reqs
            if r["updateTextStyle"].get("textStyle", {}).get("weightedFontFamily", {}).get("fontFamily") == "Courier New"
        ]
        self.assertGreaterEqual(len(font_reqs), 1, "Default code font should be Courier New")

    def test_mcp_write_to_tab_not_found_does_not_audit(self):
        """The MCP wrapper must not log an audit when the underlying write returns
        not_found — no write happened. Regression guard for the audit no-op (#178)."""
        import json
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

        with patch("mcp_server._write_to_tab") as mock_write, \
             patch("policy.append_audit") as mock_audit:
            mock_write.return_value = {"status": "not_found", "documentId": "doc1", "tabId": "tab.x"}
            result = mcp_server.gdocs_write_to_tab("doc1", "tab.x", "- a")

        data = json.loads(result)
        self.assertEqual(data.get("status"), "not_found")
        mock_audit.assert_not_called()


class TestDeleteTab(unittest.TestCase):
    """Gap 3a: gdocs_delete_tab issues deleteTab request; idempotent on missing tab."""

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def test_delete_tab_issues_delete_tab_request(self):
        """gdocs_delete_tab emits deleteTab (real Docs API key) with correct tabId."""
        import json

        with patch("policy.api") as mock_api:
            mock_api.return_value = {"replies": [{}]}
            result = mcp_server.gdocs_delete_tab("doc1", "tab.abc123")
            data = json.loads(result)

        self.assertNotIn("error", data)
        mock_api.assert_called_once()
        call_args = mock_api.call_args[0]
        self.assertEqual(call_args[0], "POST")
        self.assertIn("batchUpdate", call_args[1])

        body = call_args[2]
        # Bug A fix: real Docs API key is "deleteTab", not "deleteDocumentTab"
        delete_reqs = [r for r in body["requests"] if "deleteTab" in r]
        self.assertEqual(len(delete_reqs), 1)
        self.assertEqual(delete_reqs[0]["deleteTab"]["tabId"], "tab.abc123")

    def test_delete_tab_idempotent_on_missing_tab(self):
        """gdocs_delete_tab returns structured not-found, not a raised exception."""
        import json

        with patch("policy.api") as mock_api:
            mock_api.return_value = {"error": {"code": 404, "message": "Tab not found"}}
            result = mcp_server.gdocs_delete_tab("doc1", "tab.missing")
            data = json.loads(result)

        # Should return a clean structured result, not propagate 404 as an exception
        self.assertIn("status", data)
        self.assertEqual(data["status"], "not_found")

    def test_delete_tab_idempotent_on_400_tab_does_not_exist(self):
        """Live Docs API returns 400 'A tab with ID ... does not exist' for missing tabs — must map to not_found."""
        import json

        with patch("policy.api") as mock_api:
            mock_api.return_value = {"error": {
                "code": 400,
                "message": "Invalid requests[0].deleteTab: A tab with ID t.missing does not exist.",
                "status": "INVALID_ARGUMENT",
            }}
            result = mcp_server.gdocs_delete_tab("doc1", "t.missing")
            data = json.loads(result)

        self.assertNotIn("error", data, f"Expected idempotent not_found, got error envelope: {data}")
        self.assertEqual(data.get("status"), "not_found")

    def test_delete_tab_read_only_blocked(self):
        """gdocs_delete_tab honors read-only mode."""
        import json

        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_delete_tab("doc1", "tab.abc")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("Read-only", data["error"])


class TestClearTab(unittest.TestCase):
    """Gap 3b: gdocs_clear_tab issues deleteContentRange scoped to the tab."""

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def test_clear_tab_issues_delete_content_range(self):
        """gdocs_clear_tab emits deleteContentRange scoped to the tab's content."""
        import json

        mock_doc = {
            "tabs": [
                {
                    "tabProperties": {"tabId": "tab.abc", "title": "My Tab"},
                    "documentTab": {
                        "body": {
                            "content": [
                                {"startIndex": 0, "endIndex": 1},
                                {"startIndex": 1, "endIndex": 50},
                                {"startIndex": 50, "endIndex": 51},
                            ]
                        }
                    }
                }
            ]
        }

        with patch("auth.api") as mock_api:
            # First call: documents.get to find tab range; second: batchUpdate
            mock_api.side_effect = [mock_doc, {"replies": [{}]}]
            result = mcp_server.gdocs_clear_tab("doc1", "tab.abc")
            data = json.loads(result)

        self.assertNotIn("error", data)
        # Second call should be batchUpdate with deleteContentRange
        second_call = mock_api.call_args_list[1]
        body = second_call[0][2]
        delete_reqs = [r for r in body["requests"] if "deleteContentRange" in r]
        self.assertGreaterEqual(len(delete_reqs), 1)
        rng = delete_reqs[0]["deleteContentRange"]["range"]
        self.assertEqual(rng.get("tabId"), "tab.abc")
        # Range deletes through the last element's endIndex - 1 (issue #224).
        self.assertEqual(rng.get("startIndex"), 1)
        self.assertEqual(rng.get("endIndex"), 50)

    def test_clear_tab_resets_trailing_paragraph_bullet(self):
        """#301: a tab left in a list state keeps its trailing paragraph bulleted.
        clear_tab must reset that anchor (deleteParagraphBullets + NORMAL_TEXT) in
        the same batch, else re-inserting into it makes every paragraph inherit the
        bullet."""
        import json

        mock_doc = {
            "tabs": [
                {
                    "tabProperties": {"tabId": "tab.abc", "title": "My Tab"},
                    "documentTab": {
                        "body": {
                            "content": [
                                {"startIndex": 0, "endIndex": 1},
                                {"startIndex": 1, "endIndex": 50},
                                {"startIndex": 50, "endIndex": 51},
                            ]
                        }
                    }
                }
            ]
        }

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [mock_doc, {"replies": [{}]}]
            result = mcp_server.gdocs_clear_tab("doc1", "tab.abc")
            data = json.loads(result)

        self.assertNotIn("error", data)
        body = mock_api.call_args_list[1][0][2]
        reqs = body["requests"]
        # The trailing paragraph after deletion is [start_idx, start_idx+1) = [1, 2).
        del_bullets = [r for r in reqs if "deleteParagraphBullets" in r]
        self.assertEqual(len(del_bullets), 1, "must clear the trailing paragraph's bullet")
        self.assertEqual(del_bullets[0]["deleteParagraphBullets"]["range"],
                         {"startIndex": 1, "endIndex": 2, "tabId": "tab.abc"})
        normal = [
            r for r in reqs
            if "updateParagraphStyle" in r
            and r["updateParagraphStyle"]["paragraphStyle"].get("namedStyleType") == "NORMAL_TEXT"
            and r["updateParagraphStyle"]["range"] == {"startIndex": 1, "endIndex": 2, "tabId": "tab.abc"}
        ]
        self.assertEqual(len(normal), 1, "must reset the trailing paragraph to NORMAL_TEXT")

    def test_clear_tab_idempotent_on_already_empty(self):
        """gdocs_clear_tab returns clean 'already_empty' when tab has only the trailing paragraph."""
        import json

        mock_doc = {
            "tabs": [
                {
                    "tabProperties": {"tabId": "tab.empty", "title": "Empty Tab"},
                    "documentTab": {
                        "body": {
                            "content": [
                                # Only the trailing paragraph — nothing to delete
                                {"startIndex": 0, "endIndex": 1},
                            ]
                        }
                    }
                }
            ]
        }

        with patch("auth.api") as mock_api:
            mock_api.return_value = mock_doc
            result = mcp_server.gdocs_clear_tab("doc1", "tab.empty")
            data = json.loads(result)

        self.assertIn("status", data)
        self.assertEqual(data["status"], "already_empty")

    def test_clear_tab_idempotent_on_missing_tab(self):
        """gdocs_clear_tab returns structured not-found when tab doesn't exist in doc."""
        import json

        mock_doc = {
            "tabs": [
                {
                    "tabProperties": {"tabId": "tab.other", "title": "Other Tab"},
                    "documentTab": {"body": {"content": []}}
                }
            ]
        }

        with patch("auth.api") as mock_api:
            mock_api.return_value = mock_doc
            result = mcp_server.gdocs_clear_tab("doc1", "tab.nonexistent")
            data = json.loads(result)

        self.assertIn("status", data)
        self.assertEqual(data["status"], "not_found")

    def test_clear_tab_nested_subtab(self):
        """gdocs_clear_tab finds a subtab nested under parent.childTabs (Bug B fix)."""
        import json

        # Subtab "t.child" lives under parent "t.parent" in childTabs — not in top-level tabs.
        mock_doc = {
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.parent", "title": "Parent Tab"},
                    "childTabs": [
                        {
                            "tabProperties": {
                                "tabId": "t.child",
                                "title": "Child Tab",
                                "parentTabId": "t.parent",
                            },
                            "documentTab": {
                                "body": {
                                    "content": [
                                        {"startIndex": 0, "endIndex": 1},
                                        {"startIndex": 1, "endIndex": 42},
                                        {"startIndex": 42, "endIndex": 43},
                                    ]
                                }
                            },
                        }
                    ],
                    "documentTab": {
                        "body": {
                            "content": [
                                {"startIndex": 0, "endIndex": 1},
                            ]
                        }
                    },
                }
            ]
        }

        with patch("auth.api") as mock_api:
            # First call: documents.get; second: batchUpdate
            mock_api.side_effect = [mock_doc, {"replies": [{}]}]
            result = mcp_server.gdocs_clear_tab("doc1", "t.child")
            data = json.loads(result)

        self.assertNotIn("error", data)
        self.assertEqual(data.get("status"), "cleared")
        # batchUpdate call must target the child tab's range
        second_call = mock_api.call_args_list[1]
        body = second_call[0][2]
        delete_reqs = [r for r in body["requests"] if "deleteContentRange" in r]
        self.assertGreaterEqual(len(delete_reqs), 1)
        rng = delete_reqs[0]["deleteContentRange"]["range"]
        self.assertEqual(rng.get("tabId"), "t.child")
        # Range deletes through the last element's endIndex - 1 (issue #224).
        self.assertEqual(rng.get("startIndex"), 1)
        self.assertEqual(rng.get("endIndex"), 42)

    def test_clear_tab_deletes_trailing_paragraph_text(self):
        """Regression #224: clear_tab deletes through the final non-empty paragraph.

        A nested sub-tab whose LAST element is a non-empty paragraph must be
        fully cleared (endIndex - 1), not left with residue that write_to_tab
        would then append onto.
        """
        import json

        mock_doc = {
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.parent", "title": "Parent Tab"},
                    "childTabs": [
                        {
                            "tabProperties": {
                                "tabId": "t.child",
                                "title": "Child Tab",
                                "parentTabId": "t.parent",
                            },
                            "documentTab": {
                                "body": {
                                    "content": [
                                        {"startIndex": 0, "endIndex": 1},
                                        {"startIndex": 1, "endIndex": 13},  # 'old residue\n'
                                    ]
                                }
                            },
                        }
                    ],
                    "documentTab": {
                        "body": {
                            "content": [
                                {"startIndex": 0, "endIndex": 1},
                            ]
                        }
                    },
                }
            ]
        }

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [mock_doc, {"replies": [{}]}]
            result = mcp_server.gdocs_clear_tab("doc1", "t.child")
            data = json.loads(result)

        self.assertNotIn("error", data)
        self.assertEqual(data.get("status"), "cleared")
        rng = mock_api.call_args_list[1][0][2]["requests"][0]["deleteContentRange"]["range"]
        self.assertEqual(rng.get("startIndex"), 1)
        self.assertEqual(rng.get("endIndex"), 12)
        self.assertEqual(rng.get("tabId"), "t.child")

    def test_clear_tab_read_only_blocked(self):
        """gdocs_clear_tab honors read-only mode."""
        import json

        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_clear_tab("doc1", "tab.abc")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("Read-only", data["error"])


class TestRenameTab(unittest.TestCase):
    """Gap 4: gdocs_rename_tab issues updateDocumentTabProperties with tabId inside tabProperties."""

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def test_rename_tab_issues_update_document_tab_properties(self):
        """gdocs_rename_tab emits updateDocumentTabProperties with tabId inside tabProperties."""
        import json

        with patch("policy.api") as mock_api:
            mock_api.return_value = {"replies": [{}]}
            result = mcp_server.gdocs_rename_tab("doc1", "tab.abc", "New Title")
            data = json.loads(result)

        self.assertNotIn("error", data)
        mock_api.assert_called_once()
        call_args = mock_api.call_args[0]
        self.assertEqual(call_args[0], "POST")
        self.assertIn("batchUpdate", call_args[1])

        body = call_args[2]
        # Bug C fix: real Docs API key is "updateDocumentTabProperties", not "updateDocumentTab"
        rename_reqs = [r for r in body["requests"] if "updateDocumentTabProperties" in r]
        self.assertEqual(len(rename_reqs), 1)
        req = rename_reqs[0]["updateDocumentTabProperties"]
        # tabId lives INSIDE tabProperties per UpdateDocumentTabPropertiesRequest schema
        self.assertEqual(req["tabProperties"]["tabId"], "tab.abc")
        self.assertEqual(req["tabProperties"]["title"], "New Title")
        self.assertEqual(req["fields"], "title")

    def test_rename_tab_idempotent_on_missing_tab(self):
        """gdocs_rename_tab returns structured not-found when tab doesn't exist."""
        import json

        with patch("policy.api") as mock_api:
            mock_api.return_value = {"error": {"code": 404, "message": "Tab not found"}}
            result = mcp_server.gdocs_rename_tab("doc1", "tab.missing", "New Title")
            data = json.loads(result)

        self.assertIn("status", data)
        self.assertEqual(data["status"], "not_found")

    def test_rename_tab_idempotent_on_400_tab_does_not_exist(self):
        """Live Docs API returns 400 'At tab with ID ... does not exist' for missing tabs — must map to not_found."""
        import json

        with patch("policy.api") as mock_api:
            mock_api.return_value = {"error": {
                "code": 400,
                "message": "Invalid requests[0].updateDocumentTabProperties: At tab with ID t.missing does not exist.",
                "status": "INVALID_ARGUMENT",
            }}
            result = mcp_server.gdocs_rename_tab("doc1", "t.missing", "New Title")
            data = json.loads(result)

        self.assertNotIn("error", data, f"Expected idempotent not_found, got error envelope: {data}")
        self.assertEqual(data.get("status"), "not_found")

    def test_rename_tab_read_only_blocked(self):
        """gdocs_rename_tab honors read-only mode."""
        import json

        os.environ["GDOCS_READ_ONLY"] = "true"
        result = mcp_server.gdocs_rename_tab("doc1", "tab.abc", "New Title")
        data = json.loads(result)
        self.assertIn("error", data)
        self.assertIn("Read-only", data["error"])


class TestReadDocImages(unittest.TestCase):
    """#168: read_doc surfaces inline images as placeholders and returns inlineObjects map."""

    def _make_doc_resp(self, elements, inline_objects=None):
        """Build a minimal Docs API response dict with the given paragraph elements."""
        return {
            "documentId": "doc1",
            "title": "Test Doc",
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": elements,
                        }
                    }
                ]
            },
            "inlineObjects": inline_objects or {},
        }

    def _make_tab_doc_resp(self, elements, inline_objects=None):
        """Build a minimal Docs API response dict with one tab containing the given elements."""
        return {
            "documentId": "doc1",
            "title": "Test Doc",
            "tabs": [
                {
                    "tabProperties": {
                        "tabId": "t.abc",
                        "title": "Tab 1",
                        "index": 0,
                    },
                    "documentTab": {
                        "body": {
                            "content": [
                                {
                                    "paragraph": {
                                        "elements": elements,
                                    }
                                }
                            ]
                        }
                    },
                    "childTabs": [],
                }
            ],
            "inlineObjects": inline_objects or {},
        }

    def test_read_doc_emits_placeholder_for_inline_image(self):
        """read_doc inserts [image: kix.abc] between surrounding textRun fragments."""
        import json

        elements = [
            {"textRun": {"content": "before "}},
            {"inlineObjectElement": {"inlineObjectId": "kix.abc"}},
            {"textRun": {"content": " after"}},
        ]
        resp = self._make_doc_resp(elements)

        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = docs_read.read_doc("doc1")

        text = result.get("text", "")
        # The placeholder must appear between the surrounding text
        self.assertIn("[image: kix.abc]", text, f"Expected placeholder in text; got: {text!r}")
        before_idx = text.index("before ")
        placeholder_idx = text.index("[image: kix.abc]")
        after_idx = text.index(" after")
        self.assertLess(before_idx, placeholder_idx)
        self.assertLess(placeholder_idx, after_idx)

    def test_read_doc_returns_inline_objects_map(self):
        """read_doc includes an inlineObjects dict with uri, width, height, description, title."""
        import json

        elements = [
            {"inlineObjectElement": {"inlineObjectId": "kix.abc"}},
        ]
        inline_objects = {
            "kix.abc": {
                "inlineObjectProperties": {
                    "embeddedObject": {
                        "imageProperties": {
                            "contentUri": "https://lh3.googleusercontent.com/abc",
                        },
                        "size": {
                            "width": {"magnitude": 200.0, "unit": "PT"},
                            "height": {"magnitude": 150.0, "unit": "PT"},
                        },
                        "description": "My image description",
                        "title": "My image title",
                    }
                }
            }
        }
        resp = self._make_doc_resp(elements, inline_objects)

        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = docs_read.read_doc("doc1")

        self.assertIn("inlineObjects", result, "read_doc result must have inlineObjects key")
        obj = result["inlineObjects"].get("kix.abc")
        self.assertIsNotNone(obj, "kix.abc must be in inlineObjects")
        self.assertEqual(obj["uri"], "https://lh3.googleusercontent.com/abc")
        self.assertEqual(obj["width"], 200.0)
        self.assertEqual(obj["height"], 150.0)
        self.assertEqual(obj["description"], "My image description")
        self.assertEqual(obj["title"], "My image title")
        # mimeType is always present (may be None)
        self.assertIn("mimeType", obj)

    def test_read_doc_without_images_unchanged(self):
        """read_doc with no inlineObjects returns inlineObjects={} and no [image: placeholder."""
        elements = [
            {"textRun": {"content": "Hello world\n"}},
        ]
        resp = self._make_doc_resp(elements, inline_objects={})

        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = docs_read.read_doc("doc1")

        self.assertEqual(result.get("inlineObjects"), {})
        text = result.get("text", "")
        self.assertNotIn("[image: ", text, f"No image placeholder expected; got: {text!r}")

    def test_read_doc_handles_image_in_tab_body(self):
        """read_doc surfaces [image: kix.tab] placeholder in per-tab text field."""
        elements = [
            {"textRun": {"content": "tab-before "}},
            {"inlineObjectElement": {"inlineObjectId": "kix.tab"}},
            {"textRun": {"content": " tab-after"}},
        ]
        resp = self._make_tab_doc_resp(elements)

        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = docs_read.read_doc("doc1")

        tabs = result.get("tabs", [])
        self.assertEqual(len(tabs), 1, "Expected one tab in result")
        tab_text = tabs[0].get("text", "")
        self.assertIn("[image: kix.tab]", tab_text,
                      f"Expected placeholder in tab text; got: {tab_text!r}")

    def test_read_doc_extracts_inline_objects_from_per_tab_location(self):
        """Live API behavior: with ?includeTabsContent=true the Docs API nests inlineObjects
        inside tab.documentTab.inlineObjects rather than at the top level. read_doc must
        collect from there, not just the top level."""
        elements = [
            {"textRun": {"content": "x "}},
            {"inlineObjectElement": {"inlineObjectId": "kix.live"}},
            {"textRun": {"content": " y"}},
        ]
        # Build doc with inlineObjects ONLY inside tab.documentTab (not top-level).
        resp = {
            "documentId": "doc1",
            "title": "Test Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.abc", "title": "Tab 1", "index": 0},
                    "documentTab": {
                        "body": {
                            "content": [{"paragraph": {"elements": elements}}]
                        },
                        "inlineObjects": {
                            "kix.live": {
                                "inlineObjectProperties": {
                                    "embeddedObject": {
                                        "imageProperties": {"contentUri": "https://lh3.google/abc"},
                                        "size": {"width": {"magnitude": 100}, "height": {"magnitude": 50}},
                                        "title": "T", "description": "D",
                                    }
                                }
                            }
                        },
                    },
                    "childTabs": [],
                }
            ],
            # NOTE: no top-level inlineObjects — this is what the live API returns
        }

        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = docs_read.read_doc("doc1")

        inline = result.get("inlineObjects", {})
        self.assertIn("kix.live", inline, f"Expected per-tab inlineObject in result; got: {list(inline.keys())}")
        self.assertEqual(inline["kix.live"]["uri"], "https://lh3.google/abc")
        self.assertEqual(inline["kix.live"]["width"], 100)

    def test_read_doc_extracts_table_cells_from_nested_tab(self):
        """Nested-tab table cell text is included in that tab's readable text."""
        table = {
            "table": {
                "tableRows": [
                    {
                        "tableCells": [
                            {"content": [{"paragraph": {"elements": [{"textRun": {"content": "H1"}}]}}]},
                            {"content": [{"paragraph": {"elements": [{"textRun": {"content": "H2"}}]}}]},
                        ]
                    },
                    {
                        "tableCells": [
                            {"content": [{"paragraph": {"elements": [{"textRun": {"content": "r1c1"}}]}}]},
                            {"content": [{"paragraph": {"elements": [{"textRun": {"content": "r1c2"}}]}}]},
                        ]
                    },
                ]
            }
        }
        resp = {
            "documentId": "doc1",
            "title": "Test Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.parent", "title": "Parent", "index": 0},
                    "documentTab": {"body": {"content": []}},
                    "childTabs": [
                        {
                            "tabProperties": {"tabId": "t.child", "title": "Child", "parentTabId": "t.parent"},
                            "documentTab": {"body": {"content": [table]}},
                        }
                    ],
                }
            ],
        }

        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = docs_read.read_doc("doc1")

        child_text = result["tabs"][0]["childTabs"][0]["text"]
        for expected in ("H1", "H2", "r1c1", "r1c2"):
            self.assertIn(expected, child_text)

    def test_read_doc_extracts_table_cells_from_deeply_nested_tab(self):
        """#216: table cell text surfaces at ANY nesting depth, not just childTabs[0].

        The nested-tab table read must recurse to arbitrary depth — here the table
        lives in a grandchild tab (parent -> child -> grandchild). A read path that
        only handled top-level or one-level-deep tabs would return the surrounding
        prose but silently drop the table cells (the #216 defect, read-side twin of
        the #198 write-side flat-scan bug)."""
        table = {
            "table": {
                "tableRows": [
                    {
                        "tableCells": [
                            {"content": [{"paragraph": {"elements": [{"textRun": {"content": "alpha-team"}}]}}]},
                            {"content": [{"paragraph": {"elements": [{"textRun": {"content": "roadmap"}}]}}]},
                        ]
                    },
                    {
                        "tableCells": [
                            {"content": [{"paragraph": {"elements": [{"textRun": {"content": "beta-team"}}]}}]},
                            {"content": [{"paragraph": {"elements": [{"textRun": {"content": "deep-cell"}}]}}]},
                        ]
                    },
                ]
            }
        }
        resp = {
            "documentId": "doc1",
            "title": "Test Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.parent", "title": "Parent", "index": 0},
                    "documentTab": {"body": {"content": []}},
                    "childTabs": [
                        {
                            "tabProperties": {"tabId": "t.child", "title": "Child", "parentTabId": "t.parent"},
                            "documentTab": {"body": {"content": []}},
                            "childTabs": [
                                {
                                    "tabProperties": {"tabId": "t.grandchild", "title": "Grandchild", "parentTabId": "t.child"},
                                    "documentTab": {"body": {"content": [table]}},
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = docs_read.read_doc("doc1")

        grandchild = result["tabs"][0]["childTabs"][0]["childTabs"][0]
        self.assertEqual(grandchild["nestingLevel"], 2)
        for expected in ("alpha-team", "roadmap", "beta-team", "deep-cell"):
            self.assertIn(expected, grandchild["text"])

    def test_read_doc_extracts_images_inside_table_cells(self):
        """Table-cell inline images get the same placeholder + metadata treatment."""
        table = {
            "table": {
                "tableRows": [
                    {
                        "tableCells": [
                            {
                                "content": [
                                    {
                                        "paragraph": {
                                            "elements": [
                                                {"textRun": {"content": "Logo "}},
                                                {"inlineObjectElement": {"inlineObjectId": "kix.logo"}},
                                            ]
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        }
        resp = {
            "documentId": "doc1",
            "title": "Test Doc",
            "tabs": [
                {
                    "tabProperties": {"tabId": "t.abc", "title": "Tab", "index": 0},
                    "documentTab": {
                        "body": {"content": [table]},
                        "inlineObjects": {
                            "kix.logo": {
                                "inlineObjectProperties": {
                                    "embeddedObject": {
                                        "imageProperties": {"contentUri": "https://lh3.google/logo"},
                                        "size": {"width": {"magnitude": 120}, "height": {"magnitude": 40}},
                                    }
                                }
                            }
                        },
                    },
                }
            ],
        }

        with patch("auth.api") as mock_api:
            mock_api.return_value = resp
            result = docs_read.read_doc("doc1")

        tab_text = result["tabs"][0]["text"]
        self.assertIn("[image: kix.logo]", tab_text)
        self.assertEqual(result["inlineObjects"]["kix.logo"]["uri"], "https://lh3.google/logo")


class TestGetImage(unittest.TestCase):
    """#168: get_image_bytes fetches inline image bytes as base64."""

    def _make_doc_with_image(self, object_id, content_uri):
        """Build minimal Docs API response with one inlineObject."""
        return {
            "documentId": "doc1",
            "inlineObjects": {
                object_id: {
                    "inlineObjectProperties": {
                        "embeddedObject": {
                            "imageProperties": {
                                "contentUri": content_uri,
                            }
                        }
                    }
                }
            },
        }

    def test_get_image_returns_base64_and_mimetype(self):
        """get_image_bytes returns base64-encoded bytes and mimeType from Content-Type."""
        import base64

        doc_resp = self._make_doc_with_image("kix.img1", "https://lh3.googleusercontent.com/img1")

        with patch("auth.api") as mock_api, \
             patch("auth._fetch_authed_bytes") as mock_fetch:
            mock_api.return_value = doc_resp
            mock_fetch.return_value = (b"fakepng", "image/png")

            result = docs_read.get_image_bytes("doc1", "kix.img1")

        self.assertNotIn("status", result, f"Expected success result; got: {result}")
        self.assertEqual(result["mimeType"], "image/png")
        self.assertEqual(result["documentId"], "doc1")
        self.assertEqual(result["objectId"], "kix.img1")
        expected_data = base64.b64encode(b"fakepng").decode("ascii")
        self.assertEqual(result["data"], expected_data)
        mock_fetch.assert_called_once_with("https://lh3.googleusercontent.com/img1")

    def test_get_image_missing_object_id(self):
        """get_image_bytes returns not_found when objectId is absent from inlineObjects."""
        doc_resp = {
            "documentId": "doc1",
            "inlineObjects": {},
        }

        with patch("auth.api") as mock_api:
            mock_api.return_value = doc_resp
            result = docs_read.get_image_bytes("doc1", "kix.missing")

        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["documentId"], "doc1")
        self.assertEqual(result["objectId"], "kix.missing")

    def test_get_image_finds_object_in_tab_documentTab(self):
        """Live API behavior: with ?includeTabsContent=true the Docs API nests inlineObjects
        inside tab.documentTab.inlineObjects. get_image_bytes must search there, not just
        the top level."""
        import base64

        doc_resp = {
            "documentId": "doc1",
            "tabs": [
                {
                    "documentTab": {
                        "inlineObjects": {
                            "kix.intab": {
                                "inlineObjectProperties": {
                                    "embeddedObject": {
                                        "imageProperties": {
                                            "contentUri": "https://lh3.googleusercontent.com/intab",
                                        }
                                    }
                                }
                            }
                        }
                    },
                    "childTabs": [],
                }
            ],
            # NOTE: no top-level inlineObjects
        }

        with patch("auth.api") as mock_api, \
             patch("auth._fetch_authed_bytes") as mock_fetch:
            mock_api.return_value = doc_resp
            mock_fetch.return_value = (b"intabpng", "image/png")

            result = docs_read.get_image_bytes("doc1", "kix.intab")

        self.assertNotIn("status", result, f"Expected success; got: {result}")
        self.assertEqual(result["objectId"], "kix.intab")
        self.assertEqual(result["data"], base64.b64encode(b"intabpng").decode("ascii"))

    def test_get_image_object_id_without_content_uri(self):
        """get_image_bytes returns not_found when contentUri is absent."""
        doc_resp = {
            "documentId": "doc1",
            "inlineObjects": {
                "kix.nouri": {
                    "inlineObjectProperties": {
                        "embeddedObject": {
                            "imageProperties": {}  # no contentUri
                        }
                    }
                }
            },
        }

        with patch("auth.api") as mock_api:
            mock_api.return_value = doc_resp
            result = docs_read.get_image_bytes("doc1", "kix.nouri")

        self.assertEqual(result["status"], "not_found")


class TestWriteToTabIdempotency(unittest.TestCase):
    """write_to_tab must be idempotent: re-running with the same content yields the same
    visible document. Mechanism: clear the tab's existing content before inserting, so a
    re-run replaces rather than prepends (which would double the content). See #178.
    """

    @staticmethod
    def _ordered_request_kinds(mock_api):
        """Flatten every batchUpdate request kind across POST calls, in call order."""
        kinds = []
        for call in mock_api.call_args_list:
            args = call[0]
            if not args or args[0] != "POST":
                continue
            data = args[2] if len(args) > 2 else (call.kwargs.get("data") or {})
            for req in (data or {}).get("requests", []):
                kinds.extend(req.keys())
        return kinds

    @staticmethod
    def _tab_with_content(tab_id):
        """A tab whose body has deletable content (section break + paragraph + trailing)."""
        return {
            "tabs": [{
                "tabProperties": {"tabId": tab_id},
                "documentTab": {"body": {"content": [
                    {"startIndex": 0, "endIndex": 1},                       # section break
                    {"startIndex": 1, "endIndex": 30, "paragraph": {}},     # existing content
                    {"startIndex": 30, "endIndex": 31, "paragraph": {}},    # trailing paragraph
                ]}},
            }]
        }

    def test_write_to_tab_clears_existing_content_before_inserting(self):
        """A re-run must delete the tab's existing content BEFORE inserting the new
        content — otherwise the content is doubled (prepend bug)."""
        mock_doc = self._tab_with_content("tab.x")

        def fake_api(method, url, data=None):
            return mock_doc if method == "GET" else {}

        with patch("auth.api") as mock_api:
            mock_api.side_effect = fake_api
            docs_write.write_to_tab("doc1", "tab.x", "- a\n- b\n- c")

        kinds = self._ordered_request_kinds(mock_api)
        self.assertIn("deleteContentRange", kinds, "write_to_tab must clear before insert")
        self.assertIn("insertText", kinds, "write_to_tab must still insert content")
        self.assertLess(
            kinds.index("deleteContentRange"), kinds.index("insertText"),
            "clear must happen BEFORE insert, else content is prepended/doubled",
        )

    def test_write_to_tab_missing_tab_returns_not_found(self):
        """Writing to a tab that doesn't exist returns a clean not_found (idempotency
        bonus, aligns with #162) and inserts nothing."""
        mock_doc = self._tab_with_content("tab.other")  # different id than we write to

        def fake_api(method, url, data=None):
            return mock_doc if method == "GET" else {}

        with patch("auth.api") as mock_api:
            mock_api.side_effect = fake_api
            result = docs_write.write_to_tab("doc1", "tab.missing", "- a\n- b")

        self.assertEqual(result.get("status"), "not_found")
        kinds = self._ordered_request_kinds(mock_api)
        self.assertNotIn("insertText", kinds, "must not insert into a missing tab")
        self.assertNotIn("deleteContentRange", kinds)

    def test_write_to_tab_already_empty_tab_inserts_without_delete(self):
        """An empty tab (only the trailing paragraph) needs no delete — just insert."""
        mock_doc = {
            "tabs": [{
                "tabProperties": {"tabId": "tab.empty"},
                "documentTab": {"body": {"content": [
                    {"startIndex": 0, "endIndex": 1},  # only the trailing paragraph
                ]}},
            }]
        }

        def fake_api(method, url, data=None):
            return mock_doc if method == "GET" else {}

        with patch("auth.api") as mock_api:
            mock_api.side_effect = fake_api
            result = docs_write.write_to_tab("doc1", "tab.empty", "- a\n- b")

        kinds = self._ordered_request_kinds(mock_api)
        self.assertNotIn("deleteContentRange", kinds, "empty tab needs no clear")
        self.assertIn("insertText", kinds)
        self.assertEqual(result.get("status"), "written")


class TestImageDestructionGate(unittest.TestCase):
    """#311: clearing/overwriting a tab that holds embedded images must refuse by
    default (naming the objectIds + workaround tools) and require an explicit opt-in.

    Google Docs cannot re-anchor an inline image once its bytes are gone, so a blind
    clear+rebuild silently destroys any embedded image. These tests lock the guard on
    the shared clear helper, on write_to_tab, and at the MCP tool boundary — including
    the nested-sub-tab and images-in-table-cell shapes and the no-images passthrough.
    """

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    @staticmethod
    def _tab_with_image(tab_id="tab.img", object_id="kix.pic", nested=False):
        """A doc whose tab body has a paragraph containing an embedded inline image."""
        document_tab = {
            "body": {"content": [
                {"startIndex": 0, "endIndex": 1},
                {"startIndex": 1, "endIndex": 20, "paragraph": {"elements": [
                    {"inlineObjectElement": {"inlineObjectId": object_id}},
                ]}},
                {"startIndex": 20, "endIndex": 21, "paragraph": {}},
            ]}
        }
        tab = {"tabProperties": {"tabId": tab_id}, "documentTab": document_tab}
        if nested:
            return {"tabs": [{
                "tabProperties": {"tabId": "t.parent"},
                "documentTab": {"body": {"content": [{"startIndex": 0, "endIndex": 1}]}},
                "childTabs": [dict(tab, tabProperties={"tabId": tab_id, "parentTabId": "t.parent"})],
            }]}
        return {"tabs": [tab]}

    def test_clear_helper_refuses_tab_with_image_by_default(self):
        """clear_tab_content refuses (no batchUpdate) when the tab holds an image."""
        mock_doc = self._tab_with_image(object_id="kix.pic")

        with patch("auth.api") as mock_api:
            mock_api.return_value = mock_doc  # only the GET should happen
            result = docs_write.clear_tab_content("doc1", "tab.img")

        self.assertEqual(result.get("status"), "blocked_image_destruction")
        self.assertEqual(result.get("imageObjectIds"), ["kix.pic"])
        self.assertIn("kix.pic", result["error"])
        self.assertIn("allow_image_destruction", result["error"])
        # No batchUpdate (POST) — nothing was destroyed.
        self.assertTrue(all(c[0][0] == "GET" for c in mock_api.call_args_list),
                        "refusal must not issue any write/delete call")

    def test_clear_helper_opt_in_proceeds(self):
        """allow_image_destruction=True clears the tab (image lost) and issues delete."""
        mock_doc = self._tab_with_image(object_id="kix.pic")

        with patch("auth.api") as mock_api:
            mock_api.side_effect = [mock_doc, {"replies": [{}]}]
            result = docs_write.clear_tab_content("doc1", "tab.img", allow_image_destruction=True)

        self.assertEqual(result.get("status"), "cleared")
        body = mock_api.call_args_list[1][0][2]
        self.assertTrue(any("deleteContentRange" in r for r in body["requests"]))

    def test_clear_helper_detects_image_in_nested_subtab(self):
        """The guard must recurse the tab tree — an image in a nested sub-tab still blocks."""
        mock_doc = self._tab_with_image(tab_id="t.child", object_id="kix.deep", nested=True)

        with patch("auth.api") as mock_api:
            mock_api.return_value = mock_doc
            result = docs_write.clear_tab_content("doc1", "t.child")

        self.assertEqual(result.get("status"), "blocked_image_destruction")
        self.assertEqual(result.get("imageObjectIds"), ["kix.deep"])

    def test_clear_helper_detects_image_inside_table_cell(self):
        """An image embedded in a table cell must also be detected and block the clear."""
        mock_doc = {"tabs": [{
            "tabProperties": {"tabId": "tab.tbl"},
            "documentTab": {"body": {"content": [
                {"startIndex": 0, "endIndex": 1},
                {"table": {"tableRows": [{"tableCells": [{"content": [
                    {"paragraph": {"elements": [
                        {"inlineObjectElement": {"inlineObjectId": "kix.cell"}},
                    ]}},
                ]}]}]}},
                {"startIndex": 40, "endIndex": 41, "paragraph": {}},
            ]}},
        }]}

        with patch("auth.api") as mock_api:
            mock_api.return_value = mock_doc
            result = docs_write.clear_tab_content("doc1", "tab.tbl")

        self.assertEqual(result.get("status"), "blocked_image_destruction")
        self.assertEqual(result.get("imageObjectIds"), ["kix.cell"])

    def test_write_to_tab_refuses_and_inserts_nothing(self):
        """write_to_tab on an image-bearing tab refuses and performs no delete/insert."""
        mock_doc = self._tab_with_image(object_id="kix.pic")

        def fake_api(method, url, data=None):
            return mock_doc if method == "GET" else {}

        with patch("auth.api") as mock_api:
            mock_api.side_effect = fake_api
            result = docs_write.write_to_tab("doc1", "tab.img", "# new content")

        self.assertEqual(result.get("status"), "blocked_image_destruction")
        self.assertIn("kix.pic", result.get("imageObjectIds", []))
        # Nothing mutated the doc.
        self.assertTrue(all(c[0][0] == "GET" for c in mock_api.call_args_list),
                        "a blocked write must not clear or insert")

    def test_write_to_tab_opt_in_overwrites(self):
        """allow_image_destruction=True lets write_to_tab clear (losing the image) + insert."""
        mock_doc = self._tab_with_image(object_id="kix.pic")

        def fake_api(method, url, data=None):
            return mock_doc if method == "GET" else {}

        with patch("auth.api") as mock_api:
            mock_api.side_effect = fake_api
            result = docs_write.write_to_tab(
                "doc1", "tab.img", "# new content", allow_image_destruction=True)

        self.assertEqual(result.get("status"), "written")

    def test_write_to_tab_without_images_passthrough(self):
        """A tab with no images writes normally — the guard is a no-op there."""
        mock_doc = {"tabs": [{
            "tabProperties": {"tabId": "tab.txt"},
            "documentTab": {"body": {"content": [
                {"startIndex": 0, "endIndex": 1},
                {"startIndex": 1, "endIndex": 30, "paragraph": {}},
                {"startIndex": 30, "endIndex": 31, "paragraph": {}},
            ]}},
        }]}

        def fake_api(method, url, data=None):
            return mock_doc if method == "GET" else {}

        with patch("auth.api") as mock_api:
            mock_api.side_effect = fake_api
            result = docs_write.write_to_tab("doc1", "tab.txt", "# hello")

        self.assertEqual(result.get("status"), "written")

    def test_mcp_write_to_tab_blocked_does_not_audit(self):
        """The MCP tool surfaces the refusal JSON and records no audit entry."""
        mock_doc = self._tab_with_image(object_id="kix.pic")

        def fake_api(method, url, data=None):
            return mock_doc if method == "GET" else {}

        with patch("auth.api") as mock_api, patch("policy.append_audit") as mock_audit:
            mock_api.side_effect = fake_api
            out = json.loads(mcp_server.gdocs_write_to_tab("doc1", "tab.img", "# new"))

        self.assertEqual(out.get("status"), "blocked_image_destruction")
        mock_audit.assert_not_called()

    def test_mcp_clear_tab_blocked_by_default(self):
        """gdocs_clear_tab refuses by default and passes allow_image_destruction through."""
        mock_doc = self._tab_with_image(object_id="kix.pic")

        # Default: refuse.
        with patch("auth.api") as mock_api:
            mock_api.return_value = mock_doc
            blocked = json.loads(mcp_server.gdocs_clear_tab("doc1", "tab.img"))
        self.assertEqual(blocked.get("status"), "blocked_image_destruction")

        # Opt-in: proceed.
        with patch("auth.api") as mock_api:
            mock_api.side_effect = [mock_doc, {"replies": [{}]}]
            cleared = json.loads(
                mcp_server.gdocs_clear_tab("doc1", "tab.img", allow_image_destruction=True))
        self.assertEqual(cleared.get("status"), "cleared")


class TestEmojiUtf16Indexing(unittest.TestCase):
    """Google Docs offsets are UTF-16 code units; an emoji (supplementary plane) counts
    as 2, but Python len() counts it as 1. Position arithmetic must use _utf16_len, else
    every index after an emoji drifts by 1 and corrupts styling/bullet ranges. See #178.
    """

    def test_utf16_len_counts_supplementary_plane_as_two(self):
        from markdown_inline import _utf16_len
        self.assertEqual(_utf16_len("plain"), 5)
        self.assertEqual(_utf16_len("🎯"), 2)          # single emoji = surrogate pair
        self.assertEqual(_utf16_len("a🎯b"), 4)        # 1 + 2 + 1
        self.assertEqual(_utf16_len("✓"), 1)           # BMP check mark = 1 unit

    def test_emoji_in_heading_shifts_following_list_range_by_utf16_units(self):
        """Regression: a heading containing an emoji must advance the cursor by 2 units
        for that emoji, so the following list's bullet range starts at the right index."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "# 🎯\n\n- a\n")

        all_reqs = []
        for call in mock_api.call_args_list:
            body = call[0][2] if len(call[0]) > 2 else {}
            all_reqs.extend(body.get("requests", []))

        bullet_reqs = [r for r in all_reqs if "createParagraphBullets" in r]
        self.assertEqual(len(bullet_reqs), 1)
        start = bullet_reqs[0]["createParagraphBullets"]["range"]["startIndex"]
        # heading "🎯\n" = 🎯(2 UTF-16 units) + \n(1) = 3, inserted at index 1 → ends at 4.
        # No blank paragraph follows a heading (#2001), so the list starts at 4.
        # The buggy len()-based math would count "🎯\n" as 2 and put the bullet at 3.
        self.assertEqual(start, 4, "list range must use UTF-16 length of the emoji heading")


class TestBulletPreset(unittest.TestCase):
    """#1768: the house bullet glyph set is fixed (no bullet_preset parameter)."""

    def _collect(self, mock_api):
        reqs = []
        for call in mock_api.call_args_list:
            if len(call[0]) > 2:
                reqs.extend(call[0][2].get("requests", []))
        return reqs

    def test_default_unordered_preset_is_the_dash_fallback(self):
        """#1770: dash bullets are unreachable over batchUpdate (four probes in
        docs/research/2026-09-13-gdocs-dash-bullets.md), so the house preset is
        BULLET_ARROW_DIAMOND_DISC — the closest horizontally-oriented glyph."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "- a\n- b")

        bullets = [r for r in self._collect(mock_api) if "createParagraphBullets" in r]
        self.assertEqual(bullets[0]["createParagraphBullets"]["bulletPreset"], "BULLET_ARROW_DIAMOND_DISC")

class TestMissingTargetEnvelope(unittest.TestCase):
    """#162: tab-target tools map the live API's missing-target error (404, or
    400 'does not exist') to a clean structured not_found instead of leaking the
    raw Google error envelope. Audit fold-in from #160's 400-mapping fix."""

    def setUp(self):
        self._orig_ro = os.environ.get("GDOCS_READ_ONLY")
        os.environ["GDOCS_READ_ONLY"] = "false"
        os.environ.pop("GDOCS_ALLOWED_FOLDERS", None)

    def tearDown(self):
        if self._orig_ro is not None:
            os.environ["GDOCS_READ_ONLY"] = self._orig_ro
        elif "GDOCS_READ_ONLY" in os.environ:
            del os.environ["GDOCS_READ_ONLY"]

    def _missing_tab_400(self, target="tab"):
        return {"error": {
            "code": 400,
            "message": f"Invalid requests[0]: A {target} with ID t.missing does not exist.",
            "status": "INVALID_ARGUMENT",
        }}

    def test_is_missing_target_error_helper(self):
        from policy import is_missing_target_error

        self.assertTrue(is_missing_target_error({"error": {"code": 404, "message": "nope"}}))
        self.assertTrue(is_missing_target_error(self._missing_tab_400()))
        # A different 400 (not a missing target) must NOT be masked.
        self.assertFalse(is_missing_target_error({"error": {"code": 400, "message": "bad range"}}))
        # Success / non-error envelopes and non-dicts are never missing-target.
        self.assertFalse(is_missing_target_error({"replies": [{}]}))
        self.assertFalse(is_missing_target_error({"raw": "x"}))
        self.assertFalse(is_missing_target_error("not a dict"))

    def test_insert_image_missing_tab_returns_not_found(self):
        with patch("policy.api") as mock_api:
            mock_api.return_value = self._missing_tab_400()
            data = json.loads(mcp_server.gdocs_insert_image("doc1", "t.missing", "http://x/y.png", 5))
        self.assertNotIn("error", data, f"leaked raw envelope: {data}")
        self.assertEqual(data.get("status"), "not_found")
        self.assertEqual(data.get("tabId"), "t.missing")

    def test_insert_image_other_error_passes_through(self):
        """A non-missing-target error is NOT masked as not_found."""
        with patch("policy.api") as mock_api:
            mock_api.return_value = {"error": {"code": 403, "message": "permission denied"}}
            data = json.loads(mcp_server.gdocs_insert_image("doc1", "t.x", "http://x/y.png", 5))
        self.assertNotEqual(data.get("status"), "not_found")
        self.assertIn("error", data)

    def test_insert_person_missing_tab_returns_not_found(self):
        with patch("policy.api") as mock_api:
            mock_api.return_value = self._missing_tab_400()
            data = json.loads(mcp_server.gdocs_insert_person("doc1", "reader@example.com", index=5, tab_id="t.missing"))
        self.assertNotIn("error", data, f"leaked raw envelope: {data}")
        self.assertEqual(data.get("status"), "not_found")
        self.assertEqual(data.get("tabId"), "t.missing")

    def test_find_replace_missing_tab_returns_not_found(self):
        # find_replace delegates to docs_write.find_replace, which calls auth.api.
        with patch("auth.api") as mock_api:
            mock_api.return_value = self._missing_tab_400()
            data = json.loads(mcp_server.gdocs_find_replace("doc1", "a", "b", tab_id="t.missing"))
        self.assertNotIn("error", data, f"leaked raw envelope: {data}")
        self.assertEqual(data.get("status"), "not_found")
        self.assertEqual(data.get("tabId"), "t.missing")

    def test_add_tab_missing_parent_returns_not_found(self):
        with patch("auth.api") as mock_api:
            mock_api.return_value = self._missing_tab_400(target="parent tab")
            data = json.loads(mcp_server.gdocs_add_tab("doc1", "New", parent_tab_id="t.missing"))
        self.assertNotIn("error", data, f"leaked raw envelope: {data}")
        self.assertEqual(data.get("status"), "not_found")
        self.assertEqual(data.get("parentTabId"), "t.missing")


class TestInsertErrorPropagation(unittest.TestCase):
    """#423: Google API error envelopes on the insert path must be propagated,
    not discarded — a swallowed batch error used to mean silent truncation
    (partial failure) or a silent empty tab (total failure) under a "written"
    receipt."""

    @staticmethod
    def _api_error(code=500, message="backend boom"):
        return {"error": {"code": code, "message": message, "status": "INTERNAL"}}

    @staticmethod
    def _tab_with_content(tab_id):
        return {
            "tabs": [{
                "tabProperties": {"tabId": tab_id},
                "documentTab": {"body": {"content": [
                    {"startIndex": 0, "endIndex": 1},
                    {"startIndex": 1, "endIndex": 30, "paragraph": {}},
                    {"startIndex": 30, "endIndex": 31, "paragraph": {}},
                ]}},
            }]
        }

    def test_insert_markdown_batch_error_returns_insert_failed(self):
        from markdown_render import _insert_markdown
        with patch("auth.api") as mock_api:
            mock_api.return_value = self._api_error()
            result = _insert_markdown("doc1", "# Heading\n\nSome text")
        self.assertEqual(result.get("status"), "insert_failed")
        self.assertIn("backend boom", result.get("error", ""))
        self.assertEqual(result.get("apiError", {}).get("code"), 500)
        self.assertEqual(result.get("batchesCompleted"), 0)

    def test_insert_markdown_success_returns_inserted_envelope(self):
        from markdown_render import _insert_markdown
        with patch("auth.api") as mock_api:
            mock_api.return_value = {"replies": []}
            result = _insert_markdown("doc1", "# Heading\n\nSome text")
        self.assertEqual(result.get("status"), "inserted")
        self.assertGreaterEqual(result.get("batchesSent", 0), 1)
        self.assertGreaterEqual(result.get("requestsSent", 0), 1)

    def test_insert_markdown_empty_content_is_inserted_with_zero_requests(self):
        """Empty markdown renders zero requests: no API call, clean success envelope."""
        from markdown_render import _insert_markdown
        with patch("auth.api") as mock_api:
            result = _insert_markdown("doc1", "")
        self.assertEqual(result.get("status"), "inserted")
        self.assertEqual(result.get("requestsSent"), 0)
        mock_api.assert_not_called()

    def test_insert_markdown_table_phase_error_returns_insert_failed(self):
        """The table branch calls the API outside flush_requests; its errors must
        propagate too."""
        from markdown_render import _insert_markdown
        api_error = self._api_error(code=400, message="table rejected")

        def fake_api(method, url, data=None):
            reqs = (data or {}).get("requests", [])
            if any("insertTable" in r for r in reqs):
                return api_error
            return {"replies": []}

        with patch("auth.api", side_effect=fake_api):
            result = _insert_markdown("doc1", "intro\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
        self.assertEqual(result.get("status"), "insert_failed")
        self.assertIn("table rejected", result.get("error", ""))

    def test_write_to_tab_insert_error_returns_cleared_but_write_failed(self):
        """Destructive ordering fails closed: the clear already ran, so a failed
        insert must name the loss — never return "written"."""
        mock_doc = self._tab_with_content("tab.x")
        api_error = self._api_error(code=429, message="Quota exceeded")

        def fake_api(method, url, data=None):
            if method == "GET":
                return mock_doc
            reqs = (data or {}).get("requests", [])
            if any("insertText" in r for r in reqs):
                return api_error
            return {"replies": []}  # the clear batch succeeds

        with patch("auth.api", side_effect=fake_api):
            result = docs_write.write_to_tab("doc1", "tab.x", "# New content")

        self.assertEqual(result.get("status"), "cleared_but_write_failed")
        self.assertNotEqual(result.get("status"), "written")
        self.assertIn("previous content is lost", result.get("error", ""))
        self.assertIn("Quota exceeded", result.get("error", ""))
        self.assertEqual(result.get("apiError", {}).get("code"), 429)

    def test_write_to_tab_total_insert_failure_reports_empty_tab(self):
        """The silent-empty-write mode (D2): every insert batch fails → the
        envelope says the tab is empty, batchesCompleted == 0."""
        mock_doc = self._tab_with_content("tab.x")

        def fake_api(method, url, data=None):
            if method == "GET":
                return mock_doc
            reqs = (data or {}).get("requests", [])
            if any("insertText" in r for r in reqs):
                return self._api_error()
            return {"replies": []}

        with patch("auth.api", side_effect=fake_api):
            result = docs_write.write_to_tab("doc1", "tab.x", "para one")

        self.assertEqual(result.get("status"), "cleared_but_write_failed")
        self.assertEqual(result.get("batchesCompleted"), 0)
        self.assertIn("empty", result.get("error", ""))

    def test_write_to_tab_success_still_returns_written(self):
        mock_doc = self._tab_with_content("tab.x")

        def fake_api(method, url, data=None):
            return mock_doc if method == "GET" else {"replies": []}

        with patch("auth.api", side_effect=fake_api):
            result = docs_write.write_to_tab("doc1", "tab.x", "# ok")
        self.assertEqual(result.get("status"), "written")

    def test_update_doc_insert_error_returns_update_failed(self):
        def fake_api(method, url, data=None):
            if method == "GET":
                return {"body": {"content": [{"endIndex": 10}]}}
            return self._api_error()

        with patch("auth.api", side_effect=fake_api):
            result = docs_write.update_doc("doc1", "appended text")
        self.assertEqual(result.get("status"), "update_failed")
        self.assertIn("error", result)

    def test_add_tab_insert_error_returns_tab_added_but_content_failed(self):
        add_reply = {"replies": [{"addDocumentTab": {"tabProperties": {"tabId": "t.new"}}}]}

        def fake_api(method, url, data=None):
            reqs = (data or {}).get("requests", [])
            if any("addDocumentTab" in r for r in reqs):
                return add_reply
            return self._api_error()

        with patch("auth.api", side_effect=fake_api):
            result = docs_write.add_tab("doc1", "New Tab", content="# hello")
        self.assertEqual(result.get("status"), "tab_added_but_content_failed")
        self.assertEqual(result.get("tabId"), "t.new")
        self.assertIn("error", result)


class TestCreateDocMoveFailure(unittest.TestCase):
    """#421: gdocs_create must surface a failed move into GDOCS_TARGET_FOLDER_ID
    instead of reporting unqualified success while the doc sits in the Drive root."""

    def _run_create(self, move_resp, content=None, insert_resp=None):
        def fake_api(method, url, data=None):
            if method == "POST" and url.endswith("/documents"):
                return {"documentId": "d1"}
            if method == "GET" and "drive/v3/files" in url:
                return {"parents": ["rootParent"]}
            if method == "PATCH" and "drive/v3/files" in url:
                return move_resp
            # batchUpdate for content insertion
            return insert_resp if insert_resp is not None else {"replies": []}

        with patch.object(config, "TARGET_FOLDER_ID", "folder123"):
            with patch("auth.api", side_effect=fake_api) as mock_api:
                result = docs_write.create_doc("Title", content)
        return result, mock_api

    def test_move_failure_surfaces_in_envelope(self):
        move_error = {"error": {"code": 404, "message": "File not found: folder123"}}
        result, _ = self._run_create(move_error)
        self.assertEqual(result.get("status"), "created_but_move_failed")
        self.assertEqual(result.get("documentId"), "d1")  # doc DOES exist
        self.assertIn("Drive root", result.get("error", ""))
        self.assertIn("folder123", result.get("error", ""))
        self.assertEqual(result.get("moveError", {}).get("code"), 404)

    def test_move_success_returns_created(self):
        result, mock_api = self._run_create({"id": "d1", "parents": ["folder123"]})
        self.assertEqual(result.get("status"), "created")
        self.assertNotIn("error", result)
        # The move goes through auth.api (with its timeouts/retries), not raw curl.
        patch_calls = [c for c in mock_api.call_args_list if c[0][0] == "PATCH"]
        self.assertEqual(len(patch_calls), 1)
        self.assertIn("addParents=folder123", patch_calls[0][0][1])

    def test_move_and_content_both_fail(self):
        move_error = {"error": {"code": 403, "message": "insufficientPermissions"}}
        insert_error = {"error": {"code": 500, "message": "insert boom"}}
        result, _ = self._run_create(move_error, content="# body", insert_resp=insert_error)
        self.assertEqual(result.get("status"), "created_but_move_and_content_failed")
        self.assertIn("error", result)
        self.assertIn("moveError", result)

    def test_content_failure_only(self):
        insert_error = {"error": {"code": 500, "message": "insert boom"}}
        result, _ = self._run_create({"id": "d1"}, content="# body", insert_resp=insert_error)
        self.assertEqual(result.get("status"), "created_but_content_failed")
        self.assertIn("insert boom", result.get("error", ""))


class TestAuthRobustness(unittest.TestCase):
    """#423: auth failures must raise (killing one tool call), never sys.exit
    (which killed the whole MCP server); curl/gcloud get hard timeouts; the ADC
    token is cached; 429s are retried with backoff."""

    def setUp(self):
        auth.clear_token_cache()

    def tearDown(self):
        auth.clear_token_cache()

    @staticmethod
    def _completed(returncode=0, stdout="", stderr=""):
        from unittest.mock import MagicMock
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_get_token_failure_raises_instead_of_exiting(self):
        """A transient gcloud failure must not kill the server process."""
        with patch("auth.find_gcloud", return_value="/usr/bin/gcloud"), \
             patch("auth.subprocess.run", return_value=self._completed(returncode=1, stderr="no creds")):
            try:
                auth.get_token()
                self.fail("expected an exception")
            except SystemExit:
                self.fail("get_token must raise, not sys.exit — sys.exit kills the MCP server")
            except RuntimeError as e:
                self.assertIn("gcloud", str(e))

    def test_find_gcloud_missing_raises_instead_of_exiting(self):
        with patch("auth.shutil.which", return_value=None), \
             patch("auth.os.path.exists", return_value=False):
            try:
                auth.find_gcloud()
                self.fail("expected an exception")
            except SystemExit:
                self.fail("find_gcloud must raise, not sys.exit")
            except RuntimeError as e:
                self.assertIn("gcloud", str(e))

    def test_get_token_timeout_raises_runtime_error(self):
        import subprocess as sp
        with patch("auth.find_gcloud", return_value="/usr/bin/gcloud"), \
             patch("auth.subprocess.run", side_effect=sp.TimeoutExpired(cmd="gcloud", timeout=30)):
            with self.assertRaises(RuntimeError):
                auth.get_token()

    def test_get_token_is_cached(self):
        """One gcloud subprocess per TTL window, not one per API call (#423)."""
        with patch("auth.find_gcloud", return_value="/usr/bin/gcloud"), \
             patch("auth.subprocess.run", return_value=self._completed(stdout="tok-1\n")) as mock_run:
            self.assertEqual(auth.get_token(), "tok-1")
            self.assertEqual(auth.get_token(), "tok-1")
            self.assertEqual(mock_run.call_count, 1)

    def test_get_token_failure_is_not_cached(self):
        with patch("auth.find_gcloud", return_value="/usr/bin/gcloud"), \
             patch("auth.subprocess.run", return_value=self._completed(returncode=1)) as mock_run:
            with self.assertRaises(RuntimeError):
                auth.get_token()
            mock_run.return_value = self._completed(stdout="tok-2\n")
            self.assertEqual(auth.get_token(), "tok-2")
            self.assertEqual(mock_run.call_count, 2)

    def test_api_curl_includes_timeout_flags(self):
        with patch("auth.get_token", return_value="tok"), \
             patch("auth.subprocess.run", return_value=self._completed(stdout='{"ok": true}')) as mock_run:
            auth.api("GET", "https://example.com/x")
        cmd = mock_run.call_args[0][0]
        self.assertIn("--max-time", cmd)
        self.assertIn("--connect-timeout", cmd)
        self.assertIsNotNone(mock_run.call_args.kwargs.get("timeout"),
                             "subprocess.run must carry a hard timeout backstop")

    def test_api_curl_timeout_raises_runtime_error(self):
        import subprocess as sp
        with patch("auth.get_token", return_value="tok"), \
             patch("auth.subprocess.run", side_effect=sp.TimeoutExpired(cmd="curl", timeout=1)):
            with self.assertRaises(RuntimeError):
                auth.api("GET", "https://example.com/x")

    def test_api_retries_429_with_backoff_then_succeeds(self):
        rate_limited = self._completed(stdout=json.dumps(
            {"error": {"code": 429, "message": "Rate limit exceeded"}}))
        ok = self._completed(stdout=json.dumps({"replies": []}))
        with patch("auth.get_token", return_value="tok"), \
             patch("auth.time.sleep") as mock_sleep, \
             patch("auth.subprocess.run", side_effect=[rate_limited, ok]) as mock_run:
            resp = auth.api("POST", "https://example.com/x", {"requests": []})
        self.assertEqual(resp, {"replies": []})
        self.assertEqual(mock_run.call_count, 2)
        mock_sleep.assert_called()

    def test_api_gives_up_after_max_attempts_and_returns_429_envelope(self):
        """After exhausting retries the 429 envelope is RETURNED (visible to the
        insert path, which now raises on it) — not swallowed."""
        rate_limited = self._completed(stdout=json.dumps(
            {"error": {"code": 429, "message": "Rate limit exceeded"}}))
        with patch("auth.get_token", return_value="tok"), \
             patch("auth.time.sleep"), \
             patch("auth.subprocess.run", return_value=rate_limited) as mock_run:
            resp = auth.api("POST", "https://example.com/x", {"requests": []})
        self.assertEqual(resp.get("error", {}).get("code"), 429)
        self.assertEqual(mock_run.call_count, auth.API_MAX_ATTEMPTS)

    def test_api_non_429_error_is_returned_without_retry(self):
        err = self._completed(stdout=json.dumps({"error": {"code": 400, "message": "bad"}}))
        with patch("auth.get_token", return_value="tok"), \
             patch("auth.time.sleep") as mock_sleep, \
             patch("auth.subprocess.run", return_value=err) as mock_run:
            resp = auth.api("GET", "https://example.com/x")
        self.assertEqual(resp.get("error", {}).get("code"), 400)
        self.assertEqual(mock_run.call_count, 1)
        mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class TestHouseStyle(unittest.TestCase):
    """#2001: the renderer emits structure only. Paragraphs set just their named
    style (spacing, fonts and sizes come from the named styles the normalize pass
    pins), blank markdown lines survive between prose blocks but never next to a
    heading, code is Courier New at the inherited size, and table headers are
    bold + tinted + vertically centred. No presets, no knobs."""

    def _reqs(self, mock_api):
        out = []
        for call in mock_api.call_args_list:
            if call[0][0] == "POST":
                out.extend(call[0][2]["requests"])
        return out

    def _para_styles(self, reqs):
        return [r["updateParagraphStyle"] for r in reqs if "updateParagraphStyle" in r]

    def test_blank_line_becomes_one_empty_paragraph(self):
        """A blank markdown line is preserved as exactly one empty NORMAL_TEXT paragraph."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "One.\n\nTwo.\n")
        texts = [r["insertText"]["text"] for r in self._reqs(mock_api) if "insertText" in r]
        self.assertEqual(texts, ["One.\n", "\n", "Two.\n"])

    def test_blank_line_run_collapses_to_one(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "One.\n\n\n\n\nTwo.\n")
        texts = [r["insertText"]["text"] for r in self._reqs(mock_api) if "insertText" in r]
        self.assertEqual(texts, ["One.\n", "\n", "Two.\n"])

    def test_leading_blank_line_is_not_emitted(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "\n\nOne.\n")
        texts = [r["insertText"]["text"] for r in self._reqs(mock_api) if "insertText" in r]
        self.assertEqual(texts, ["One.\n"])

    def test_no_blank_paragraph_next_to_a_heading(self):
        """The heading's own space-above separates sections (#2001, house_style.json)."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "Intro.\n\n## Section\n\nProse.\n\nMore.\n")
        texts = [r["insertText"]["text"] for r in self._reqs(mock_api) if "insertText" in r]
        self.assertEqual(texts, ["Intro.\n", "Section\n", "Prose.\n", "\n", "More.\n"])

    def test_prose_after_a_list_keeps_its_blank_line(self):
        """mistune folds the blank line after a list into the list token, so the
        separator must be restored: a paragraph can only follow a list after a
        blank line (else it would be a lazy continuation of the last item)."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "- a\n- b\n\nProse.\n\n1. x\n\n## H\n")
        texts = [r["insertText"]["text"] for r in self._reqs(mock_api) if "insertText" in r]
        self.assertEqual(texts, ["a\n", "b\n", "\n", "Prose.\n", "\n", "x\n", "H\n"])

    def test_trailing_blank_line_is_not_emitted(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "One.\n\n\n")
        texts = [r["insertText"]["text"] for r in self._reqs(mock_api) if "insertText" in r]
        self.assertEqual(texts, ["One.\n"])

    def test_code_block_has_no_size_or_shading(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "```\nx\n```\n")
        reqs = self._reqs(mock_api)
        ts = [r["updateTextStyle"] for r in reqs if "updateTextStyle" in r][0]
        self.assertNotIn("fontSize", ts["textStyle"])
        ps = self._para_styles(reqs)[0]
        self.assertNotIn("shading", ps["paragraphStyle"])

    def _table_doc(self):
        return {
            "body": {"content": [
                {"startIndex": 1, "endIndex": 20, "table": {
                    "rows": 2, "columns": 2,
                    "tableRows": [
                        {"tableCells": [{"content": [{"startIndex": 3}]}, {"content": [{"startIndex": 6}]}]},
                        {"tableCells": [{"content": [{"startIndex": 10}]}, {"content": [{"startIndex": 13}]}]},
                    ],
                }},
                {"startIndex": 20, "endIndex": 21, "paragraph": {"elements": []}},
            ]},
        }

    def _cell_styles(self, mock_api):
        return [r["updateTableCellStyle"] for r in self._reqs(mock_api)
                if "updateTableCellStyle" in r]

    def test_table_header_tint_emitted_by_default(self):
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.side_effect = lambda method, url, data=None: (
                self._table_doc() if method == "GET" else {}
            )
            _insert_markdown("doc1", "| A | B |\n|---|---|\n| 1 | 2 |\n")
        tint = [c for c in self._cell_styles(mock_api) if c["fields"] == "backgroundColor"]
        self.assertEqual(len(tint), 1)
        self.assertEqual(
            tint[0]["tableCellStyle"]["backgroundColor"]["color"]["rgbColor"],
            config.TABLE_HEADER_TINT_RGB,
        )
        self.assertEqual(tint[0]["tableRange"]["columnSpan"], 2)
        self.assertEqual(tint[0]["tableRange"]["rowSpan"], 1)

    def test_every_cell_is_vertically_centred(self):
        """#1770: contentAlignment MIDDLE spans the WHOLE table (rowSpan = rows),
        not just row 0 — body cells top-aligned next to a centred header read as
        a rendering bug."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.side_effect = lambda method, url, data=None: (
                self._table_doc() if method == "GET" else {}
            )
            _insert_markdown("doc1", "| A | B |\n|---|---|\n| 1 | 2 |\n")
        mid = [c for c in self._cell_styles(mock_api) if c["fields"] == "contentAlignment"]
        self.assertEqual(len(mid), 1)
        self.assertEqual(mid[0]["tableCellStyle"]["contentAlignment"], "MIDDLE")
        self.assertEqual(mid[0]["tableRange"]["rowSpan"], 2, "spans every row")
        self.assertEqual(mid[0]["tableRange"]["columnSpan"], 2, "spans every column")
        self.assertEqual(mid[0]["tableRange"]["tableCellLocation"]["rowIndex"], 0)
        self.assertEqual(mid[0]["tableRange"]["tableCellLocation"]["columnIndex"], 0)

    def _col_props(self, mock_api):
        return [r["updateTableColumnProperties"] for r in self._reqs(mock_api)
                if "updateTableColumnProperties" in r]

    def test_table_columns_fill_the_text_width(self):
        """#1770: columns are FIXED_WIDTH and sum to pageWidth - margins,
        computed from the destination's documentStyle."""
        from markdown_render import _insert_markdown

        doc = self._table_doc()
        doc["documentStyle"] = {
            "pageSize": {"width": {"magnitude": 612, "unit": "PT"}},
            "marginLeft": {"magnitude": 72, "unit": "PT"},
            "marginRight": {"magnitude": 72, "unit": "PT"},
        }
        with patch("auth.api") as mock_api:
            mock_api.side_effect = lambda method, url, data=None: (
                doc if method == "GET" else {}
            )
            _insert_markdown("doc1", "| A | B |\n|---|---|\n| 1 | 2 |\n")
        props = self._col_props(mock_api)
        self.assertEqual(len(props), 1)
        self.assertEqual(props[0]["columnIndices"], [0, 1])
        self.assertEqual(props[0]["tableColumnProperties"]["widthType"], "FIXED_WIDTH")
        self.assertEqual(props[0]["fields"], "widthType,width")
        width = props[0]["tableColumnProperties"]["width"]["magnitude"]
        self.assertEqual(width * 2, 468, "Letter, 1in margins -> 468pt text width")

    def test_table_width_is_computed_not_hard_coded(self):
        """Different margins must yield a different width — the whole point of
        reading documentStyle rather than pinning 468pt."""
        from markdown_render import _insert_markdown

        doc = self._table_doc()
        doc["documentStyle"] = {
            "pageSize": {"width": {"magnitude": 595, "unit": "PT"}},   # A4
            "marginLeft": {"magnitude": 36, "unit": "PT"},
            "marginRight": {"magnitude": 54, "unit": "PT"},
        }
        with patch("auth.api") as mock_api:
            mock_api.side_effect = lambda method, url, data=None: (
                doc if method == "GET" else {}
            )
            _insert_markdown("doc1", "| A | B |\n|---|---|\n| 1 | 2 |\n")
        width = self._col_props(mock_api)[0]["tableColumnProperties"]["width"]["magnitude"]
        self.assertEqual(width * 2, 595 - 36 - 54)

    def test_table_width_falls_back_when_no_document_style(self):
        """A destination that reports no documentStyle still gets a full-width
        table, at the Letter/1in default."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.side_effect = lambda method, url, data=None: (
                self._table_doc() if method == "GET" else {}
            )
            _insert_markdown("doc1", "| A | B |\n|---|---|\n| 1 | 2 |\n")
        width = self._col_props(mock_api)[0]["tableColumnProperties"]["width"]["magnitude"]
        self.assertEqual(width * 2, config.FALLBACK_TEXT_WIDTH_PT)

    def test_cell_paragraphs_carry_no_paragraph_style(self):
        """Cell paragraphs inherit the pinned NORMAL_TEXT style (#2001)."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.side_effect = lambda method, url, data=None: (
                self._table_doc() if method == "GET" else {}
            )
            _insert_markdown("doc1", "| A | B |\n|---|---|\n| 1 | 2 |\n")
        self.assertEqual(self._para_styles(self._reqs(mock_api)), [])

    def test_paragraphs_set_only_their_named_style(self):
        """No #1768 rhythm: nothing but namedStyleType (plus the quote's indent and
        border) is pinned, so every paragraph inherits the pinned named styles."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "# H\n\nProse.\n\n- a\n\n> q\n\n```\nx\n```\n")
        styles = self._para_styles(self._reqs(mock_api))
        self.assertGreaterEqual(len(styles), 4)
        for ps in styles:
            for field in ("lineSpacing", "spaceAbove", "spaceBelow", "spacingMode"):
                self.assertNotIn(field, ps["paragraphStyle"])
                self.assertNotIn(field, ps["fields"].split(","))
            self.assertIn("namedStyleType", ps["fields"].split(","))

    def test_no_blank_paragraph_precedes_a_table(self):
        """PAIN-004: the blank markdown line before a table is suppressed, so the grid
        gets exactly the one empty paragraph Docs' insertTable creates."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.side_effect = lambda method, url, data=None: (
                self._table_doc() if method == "GET" else {}
            )
            _insert_markdown("doc1", "Intro.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n")
        texts = [r["insertText"]["text"] for r in self._reqs(mock_api) if "insertText" in r]
        self.assertEqual(texts[0], "Intro.\n")
        self.assertNotIn("\n", texts[1:2], "no empty paragraph may sit between prose and the table")

    def test_block_quote_gets_indent_and_left_border(self):
        """PAIN-003: block quotes are visually quoted — indented with a grey left rule."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "> quoted line\n")
        quoted = [ps for ps in self._para_styles(self._reqs(mock_api))
                  if "borderLeft" in ps["paragraphStyle"]]
        self.assertEqual(len(quoted), 1)
        body = quoted[0]["paragraphStyle"]
        self.assertEqual(body["indentStart"], {"magnitude": config.BLOCK_QUOTE_INDENT_PT, "unit": "PT"})
        self.assertEqual(body["borderLeft"], config.BLOCK_QUOTE_BORDER)
        self.assertIn("borderLeft", quoted[0]["fields"])
        italics = [r["updateTextStyle"] for r in self._reqs(mock_api) if "updateTextStyle" in r]
        self.assertTrue(any(t["textStyle"].get("italic") for t in italics))

    def test_code_runs_are_courier_new_at_the_inherited_size(self):
        """PAIN-006 (deferred shading/size): code keeps the house mono font only."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "```sql\nSELECT 1;\n```\n")
        ts = [r["updateTextStyle"] for r in self._reqs(mock_api) if "updateTextStyle" in r][0]
        self.assertEqual(ts["textStyle"]["weightedFontFamily"]["fontFamily"], config.CODE_FONT)
        self.assertNotIn("fontSize", ts["textStyle"])

    def test_quote_bullet_clear_precedes_the_quote_style(self):
        """Live regression (#1768): deleteParagraphBullets resets paragraph indentation,
        so it must run BEFORE the quote's updateParagraphStyle or the 36pt indent is lost."""
        from markdown_render import _insert_markdown

        with patch("auth.api") as mock_api:
            mock_api.return_value = {}
            _insert_markdown("doc1", "> quoted line\n")
        kinds = [next(iter(r)) for r in self._reqs(mock_api)]
        self.assertLess(kinds.index("deleteParagraphBullets"), kinds.index("updateParagraphStyle"))
