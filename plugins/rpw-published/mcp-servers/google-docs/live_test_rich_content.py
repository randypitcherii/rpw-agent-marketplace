#!/usr/bin/env python3
"""
LIVE integration tests for the Google Docs MCP rich-content path (#298).

These tests hit the real Google Docs/Drive APIs with your gcloud ADC
credentials. They are deliberately named ``live_test_*.py`` so that NO
discovery mechanism picks them up automatically:

  - the ``make check`` gate discovers google-docs suites by explicit
    ``-p 'test_*.py'`` filename patterns (see Makefile) — this file matches none;
  - unittest's default discovery pattern is ``test*.py`` — no match;
  - pytest's default collection is ``test_*.py`` / ``*_test.py`` — no match.

CI could not run them anyway (the workspace IP ACL blocks hosted runners),
but the naming keeps them out of every local gate run too.

Run manually from this directory:

    uv run --with fastmcp --with mistune --with python-dotenv \
        python -m unittest live_test_rich_content -v

Requirements:
  - valid ADC: ``gcloud auth application-default login`` with the full Docs/
    Drive scope list (#74 — Drive/Docs do not accept cloud-platform alone);
  - ``GDOCS_QUOTA_PROJECT`` set, either in the environment or via the standard
    APP_ENV env file (``~/.claude/mcp-servers/google-docs/<APP_ENV>.env``),
    which this module loads the same way ``run_mcp.py`` does.

House pattern: the suite auto-creates a scratch doc and trashes it in
``tearDownClass`` — no fixtures to manage, nothing left behind (the doc goes
to Drive trash, recoverable for 30 days if a failure needs inspecting).

Coverage (issue #298 follow-up items):
  1. clear default tab -> write nested list + table + inline image ->
     ``gdocs_read`` back and assert structure (including content AFTER the
     table/image landing after them, not inside — the index-advancement
     regression);
  2. ``gdocs_get_image`` against the objectId found via ``gdocs_read`` —
     the image must be *fetchable* (real bytes, image/* mime), not just
     present in metadata;
  2b. list-item content loss (#528): an inline image inside a list item, a
     loose (multi-paragraph) item, and an empty item — all three used to be
     dropped silently, so the live tier asserts they survive the round trip
     (and that the Docs API accepts the un-bullet/indent fix-ups at all);
  3. subtab/nested-tab case: parent tab + nested child tab, write/read both —
     recursive tab lookup and per-tab ``inlineObjects`` (nested inside
     ``tab.documentTab`` with ``?includeTabsContent=true``) are known
     regression spots (flat ``resp["tabs"]`` scans silently miss sub-tabs).
"""

import base64
import json
import os
import re
import sys
import time
import unittest
from pathlib import Path

# Match run_mcp.py: allow imports from the sibling mcp-servers dir (shared lib/),
# then load the APP_ENV-selected env file so GDOCS_QUOTA_PROJECT is present
# BEFORE config.py reads it at import time.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.env_loader import load_selected_env  # noqa: E402

load_selected_env(Path(__file__).resolve().parent)

import mcp_server  # noqa: E402  (imports config AFTER env load)

# A stable, publicly fetchable PNG the Docs API can pull server-side.
IMAGE_URL = "https://www.google.com/images/branding/googlelogo/1x/googlelogo_color_272x92dp.png"

IMAGE_PLACEHOLDER_RE = re.compile(r"\[image: ([^\]]+)\]")

DEFAULT_TAB_MARKDOWN = f"""# Rich content live test

- top level item
  - nested item with a [link](https://example.com)
    - deeper nested item
- second top level item

| Name | Role |
| --- | --- |
| Ada | Engineer |
| Grace | Admiral |

Paragraph after the table.

![live test image]({IMAGE_URL})

Text after the image.

## List item content (#528)

- item with an inline image ![list image]({IMAGE_URL}) mid-sentence
- loose item first paragraph

  loose item second paragraph
-
- item after an empty one

Text after the list.
"""

CHILD_TAB_MARKDOWN = f"""## Child tab content

- child bullet one
  - nested child bullet

![child tab image]({IMAGE_URL})

Child text after the image.
"""


def _call(tool_fn, *args, **kwargs) -> dict:
    """Invoke an MCP tool function and parse its JSON envelope."""
    raw = tool_fn(*args, **kwargs)
    return json.loads(raw)


def _fail_if_error(test: unittest.TestCase, out: dict, label: str) -> dict:
    test.assertNotIn(
        "error", out,
        f"{label} returned an error envelope (expired ADC / missing scopes? "
        f"see #74 — re-mint with the full explicit Docs+Drive scope list): {out}",
    )
    return out


class LiveRichContentRoundTrip(unittest.TestCase):
    """Ordered live sequence over one auto-created scratch doc.

    Methods are numbered because unittest runs them alphabetically; each step
    feeds the next via class attributes.
    """

    doc_id: str = ""
    default_tab_id: str = ""
    default_tab_image_id: str = ""
    parent_tab_id: str = ""
    child_tab_id: str = ""
    child_tab_image_id: str = ""

    @classmethod
    def setUpClass(cls):
        quota = os.environ.get("GDOCS_QUOTA_PROJECT", "")
        if not quota or quota == "your-gcp-project-id":
            # Loud failure, never a silent skip: live coverage that silently
            # skips is indistinguishable from live coverage that passed.
            raise RuntimeError(
                "GDOCS_QUOTA_PROJECT is not configured. Set it in the environment "
                "or in ~/.claude/mcp-servers/google-docs/<APP_ENV>.env."
            )
        title = f"rpw live-test scratch — gdocs rich content {time.strftime('%Y-%m-%d %H:%M:%S')} (auto-deleted)"
        out = _call(mcp_server.gdocs_create, title)
        if out.get("status") != "created" or not out.get("documentId"):
            raise RuntimeError(f"scratch doc creation failed: {out}")
        cls.doc_id = out["documentId"]

    @classmethod
    def tearDownClass(cls):
        if cls.doc_id:
            # Best-effort trash; a failure here must not mask test results.
            try:
                _call(mcp_server.gdocs_delete, cls.doc_id)
            except Exception as e:  # pragma: no cover - cleanup only
                print(f"WARNING: scratch doc cleanup failed for {cls.doc_id}: {e}", file=sys.stderr)

    # -- 1. clear default tab -> write rich content ---------------------------

    def test_01_clear_default_tab_then_write_rich_content(self):
        read = _fail_if_error(self, _call(mcp_server.gdocs_read, self.doc_id), "gdocs_read (initial)")
        tabs = read.get("tabs", [])
        self.assertTrue(tabs, f"new doc has no tabs in gdocs_read output: {read}")
        type(self).default_tab_id = tabs[0]["tabId"]

        cleared = _fail_if_error(
            self, _call(mcp_server.gdocs_clear_tab, self.doc_id, self.default_tab_id),
            "gdocs_clear_tab",
        )
        self.assertIn(
            cleared.get("status"), {"cleared", "already_empty"},
            f"unexpected clear_tab status: {cleared}",
        )

        written = _fail_if_error(
            self,
            _call(mcp_server.gdocs_write_to_tab, self.doc_id, self.default_tab_id, DEFAULT_TAB_MARKDOWN),
            "gdocs_write_to_tab (default tab)",
        )
        self.assertEqual(
            written.get("status"), "written",
            f"write_to_tab did not fully succeed: {written}",
        )

    # -- 2. read back and assert structure ------------------------------------

    def test_02_read_back_asserts_structure(self):
        self.assertTrue(self.default_tab_id, "test_01 must run first")
        read = _fail_if_error(self, _call(mcp_server.gdocs_read, self.doc_id), "gdocs_read (round-trip)")

        tab = next((t for t in read["tabs"] if t["tabId"] == self.default_tab_id), None)
        self.assertIsNotNone(tab, f"default tab {self.default_tab_id} missing from read: {read['tabs']}")
        text = tab["text"]

        # Nested list content (including the linked nested item's anchor text).
        for expected in (
            "top level item",
            "nested item with a link",
            "deeper nested item",
            "second top level item",
        ):
            self.assertIn(expected, text, f"list item {expected!r} missing from tab text:\n{text}")

        # Table cells come back as tab-separated rows in the plain-text read path.
        self.assertIn("Name\tRole", text, f"table header row missing/misrendered:\n{text}")
        self.assertIn("Ada\tEngineer", text, f"table data row missing/misrendered:\n{text}")
        self.assertIn("Grace\tAdmiral", text, f"table data row missing/misrendered:\n{text}")

        # Content following the table must land AFTER the table, not inside a
        # cell and not before it (current-index advancement regression, #298).
        after_table_pos = text.find("Paragraph after the table.")
        self.assertGreater(after_table_pos, -1, f"content after table missing:\n{text}")
        self.assertGreater(
            after_table_pos, text.find("Grace\tAdmiral"),
            f"content after table appears before the table's last row:\n{text}",
        )
        # And it must not be inside any cell: no tab character on its line.
        after_table_line = next(
            (ln for ln in text.splitlines() if "Paragraph after the table." in ln), "",
        )
        self.assertNotIn(
            "\t", after_table_line,
            f"content after table was rendered inside a table row: {after_table_line!r}",
        )

        # Inline image: placeholder present in text AND metadata in inlineObjects.
        matches = IMAGE_PLACEHOLDER_RE.findall(text)
        self.assertEqual(
            len(matches), 2,
            f"expected two [image: ...] placeholders in default tab (standalone + the "
            f"one inside a list item, #528), got {matches}:\n{text}",
        )
        # matches[0] is the standalone image, which comes first in the markdown;
        # matches[1] is the in-list image asserted in the #528 block below.
        type(self).default_tab_image_id = matches[0]

        inline = read.get("inlineObjects", {})
        self.assertIn(
            self.default_tab_image_id, inline,
            f"image {self.default_tab_image_id} missing from inlineObjects metadata "
            f"(per-tab inlineObjects nest inside tab.documentTab — regression?): {list(inline)}",
        )
        self.assertTrue(
            inline[self.default_tab_image_id].get("uri"),
            f"inlineObjects entry has no contentUri: {inline[self.default_tab_image_id]}",
        )

        # Content following the image must come after the placeholder.
        self.assertGreater(
            text.find("Text after the image."), text.find(f"[image: {self.default_tab_image_id}]"),
            f"content after image is not after the image placeholder:\n{text}",
        )

        # List-item content loss (#528). All three symptoms were silent: the
        # write succeeded and the doc looked plausible with the content gone.
        lines = text.splitlines()

        def line_index(needle):
            hit = [i for i, ln in enumerate(lines) if needle in ln]
            self.assertEqual(len(hit), 1, f"expected exactly one line with {needle!r}:\n{text}")
            return hit[0]

        image_item = line_index("item with an inline image")
        self.assertRegex(
            lines[image_item], IMAGE_PLACEHOLDER_RE,
            f"inline image inside a list item was dropped: {lines[image_item]!r}",
        )
        list_image_id = IMAGE_PLACEHOLDER_RE.findall(lines[image_item])[0]
        self.assertIn(
            list_image_id, inline,
            f"in-list image {list_image_id} missing from inlineObjects: {list(inline)}",
        )
        self.assertIn("mid-sentence", lines[image_item], "text after the in-list image was lost")

        # The loose item's 2nd paragraph must survive, on its own line, right
        # after the 1st — it used to be truncated away entirely.
        first_para = line_index("loose item first paragraph")
        second_para = line_index("loose item second paragraph")
        self.assertEqual(
            second_para, first_para + 1,
            f"loose list item's 2nd paragraph is missing or misplaced:\n{text}",
        )

        # The empty item keeps its own (blank) line, so the items after it are
        # not renumbered/shifted up.
        after_empty = line_index("item after an empty one")
        self.assertEqual(
            lines[after_empty - 1].strip(), "",
            f"empty list item did not keep a line of its own:\n{text}",
        )
        self.assertGreater(
            text.find("Text after the list."), text.find("item after an empty one"),
            f"content after the list did not land after it:\n{text}",
        )

    # -- 3. gdocs_get_image: image is fetchable, not just present -------------

    def test_03_get_image_returns_fetchable_bytes(self):
        self.assertTrue(self.default_tab_image_id, "test_02 must run first")
        out = _fail_if_error(
            self,
            _call(mcp_server.gdocs_get_image, self.doc_id, self.default_tab_image_id),
            "gdocs_get_image",
        )
        self.assertNotEqual(
            out.get("status"), "not_found",
            f"gdocs_get_image could not resolve objectId returned by gdocs_read: {out}",
        )
        self.assertTrue(
            str(out.get("mimeType", "")).startswith("image/"),
            f"expected an image/* mimeType, got: {out.get('mimeType')!r}",
        )
        data = base64.b64decode(out.get("data", ""))
        self.assertGreater(
            len(data), 100,
            f"fetched image payload suspiciously small ({len(data)} bytes) — not real image bytes?",
        )

    # -- 4. subtab / nested-tab case ------------------------------------------

    def test_04_subtab_write_and_read(self):
        parent = _fail_if_error(
            self,
            _call(mcp_server.gdocs_add_tab, self.doc_id, "Live Parent Tab", "Parent tab body text."),
            "gdocs_add_tab (parent)",
        )
        self.assertEqual(parent.get("status"), "tab_added", f"parent tab add failed: {parent}")
        type(self).parent_tab_id = parent["tabId"]

        child = _fail_if_error(
            self,
            _call(
                mcp_server.gdocs_add_tab, self.doc_id, "Live Child Tab",
                "", self.parent_tab_id,
            ),
            "gdocs_add_tab (child)",
        )
        self.assertEqual(child.get("status"), "tab_added", f"child sub-tab add failed: {child}")
        type(self).child_tab_id = child["tabId"]

        # Writing to a NESTED sub-tab exercises the recursive tab lookup — a
        # flat scan of resp["tabs"] would return not_found here.
        written = _fail_if_error(
            self,
            _call(mcp_server.gdocs_write_to_tab, self.doc_id, self.child_tab_id, CHILD_TAB_MARKDOWN),
            "gdocs_write_to_tab (nested sub-tab)",
        )
        self.assertEqual(
            written.get("status"), "written",
            f"write to nested sub-tab failed (recursive tab lookup regression?): {written}",
        )

    def test_05_read_back_subtab_structure(self):
        self.assertTrue(self.child_tab_id, "test_04 must run first")
        read = _fail_if_error(self, _call(mcp_server.gdocs_read, self.doc_id), "gdocs_read (subtab)")

        parent = next((t for t in read["tabs"] if t["tabId"] == self.parent_tab_id), None)
        self.assertIsNotNone(
            parent, f"parent tab missing from top-level tabs: {[t['tabId'] for t in read['tabs']]}",
        )
        self.assertIn("Parent tab body text.", parent["text"], f"parent tab content lost: {parent}")

        child = next((t for t in parent["childTabs"] if t["tabId"] == self.child_tab_id), None)
        self.assertIsNotNone(
            child,
            f"child sub-tab missing from parent.childTabs (recursive extraction regression?): "
            f"{parent['childTabs']}",
        )
        self.assertEqual(child["title"], "Live Child Tab")
        self.assertEqual(child["parentTabId"], self.parent_tab_id)
        self.assertEqual(child["nestingLevel"], 1)
        for expected in ("child bullet one", "nested child bullet", "Child text after the image."):
            self.assertIn(expected, child["text"], f"child sub-tab content missing {expected!r}: {child['text']}")

        # The child tab's image metadata must surface even though it nests at
        # tabs[i].childTabs[j].documentTab.inlineObjects (per-tab collection
        # regression: a top-level-only scan misses it).
        matches = IMAGE_PLACEHOLDER_RE.findall(child["text"])
        self.assertEqual(
            len(matches), 1,
            f"expected exactly one image placeholder in child sub-tab, got {matches}",
        )
        type(self).child_tab_image_id = matches[0]
        self.assertIn(
            self.child_tab_image_id, read.get("inlineObjects", {}),
            f"child sub-tab image missing from inlineObjects — nested per-tab "
            f"inlineObjects not collected: {list(read.get('inlineObjects', {}))}",
        )

    def test_06_get_image_from_nested_subtab(self):
        self.assertTrue(self.child_tab_image_id, "test_05 must run first")
        out = _fail_if_error(
            self,
            _call(mcp_server.gdocs_get_image, self.doc_id, self.child_tab_image_id),
            "gdocs_get_image (nested sub-tab)",
        )
        self.assertNotEqual(
            out.get("status"), "not_found",
            f"image in a NESTED sub-tab not resolvable by gdocs_get_image "
            f"(childTabs recursion regression?): {out}",
        )
        self.assertTrue(str(out.get("mimeType", "")).startswith("image/"), f"mimeType: {out.get('mimeType')!r}")
        self.assertGreater(len(base64.b64decode(out.get("data", ""))), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
