"""Unit tests: Jira response shaping — plumbing stripped, requested fields kept (#828).

Fixtures are synthetic but structurally faithful to what the live `jira-mcp`
connection returned on 2026-09-16: a `self` link and `iconUrl` on every nested
reference, `expand` at the top of each issue, and a `statusCategory` rollup
hanging off `status`. No real issue content lives in the repo — this server ships
to the public mirror.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import uc_proxy_client

import mcp_server
import response_shaping

_BASE = "https://api.atlassian.example/ex/jira/00000000-0000-0000-0000-000000000000/rest/api/3"


def _issue(key="ABC-1", *, assignee=None, description=None):
    """One Jira issue as the REST API returns it, plumbing included."""
    fields = {
        "summary": f"Summary for {key}",
        "assignee": assignee,
        "priority": {
            "self": f"{_BASE}/priority/3",
            "iconUrl": "https://example.atlassian.net/images/icons/priorities/major.svg",
            "name": "Major",
            "id": "3",
        },
        "created": "2026-09-16T17:40:04.146-0700",
        "status": {
            "self": f"{_BASE}/status/1",
            "description": "The issue is open and ready for the assignee to start work on it.",
            "iconUrl": "https://example.atlassian.net/images/icons/statuses/open.png",
            "name": "Open",
            "id": "1",
            "statusCategory": {
                "self": f"{_BASE}/statuscategory/2",
                "id": 2,
                "key": "new",
                "colorName": "blue-gray",
                "name": "To Do",
            },
        },
    }
    if description is not None:
        fields["description"] = description
    return {
        "expand": "renderedFields,names,schema,operations,editmeta,changelog,versionedRepresentations",
        "id": "7826190",
        "self": f"{_BASE}/issue/7826190",
        "key": key,
        "fields": fields,
    }


def _search_response(count=2):
    return {
        "issues": [_issue(f"ABC-{i}") for i in range(count)],
        "nextPageToken": "abcdef",
        "isLast": False,
    }


class TestJiraSearchShaping(unittest.TestCase):
    def _shape(self, envelope):
        return json.loads(
            mcp_server.shape(json.dumps(envelope), response_shaping.shape_search)
        )

    def test_strips_top_level_plumbing(self):
        issue = self._shape(_search_response())["issues"][0]
        self.assertEqual(issue["key"], "ABC-0")
        self.assertEqual(issue["id"], "7826190")
        for dropped in ("self", "expand"):
            self.assertNotIn(dropped, issue)

    def test_strips_nested_plumbing_at_every_depth(self):
        fields = self._shape(_search_response())["issues"][0]["fields"]
        self.assertEqual(fields["status"]["name"], "Open")
        self.assertNotIn("self", fields["status"])
        self.assertNotIn("iconUrl", fields["status"])
        self.assertNotIn("statusCategory", fields["status"])
        self.assertNotIn("self", fields["priority"])
        self.assertNotIn("iconUrl", fields["priority"])

    def test_keeps_a_requested_field_that_came_back_null(self):
        # "unassigned" and "I did not ask for assignee" are different answers, so
        # a requested field stays present even when Jira returned null.
        fields = self._shape(_search_response())["issues"][0]["fields"]
        self.assertIn("assignee", fields)
        self.assertIsNone(fields["assignee"])

    def test_keeps_an_issue_description(self):
        # `description` is deliberately NOT in the plumbing set: a deep drop
        # cannot tell status boilerplate from the issue's own body, and losing an
        # issue's description to save bytes is the failure this shaping avoids.
        body = {"type": "doc", "version": 1, "content": [{"type": "paragraph"}]}
        out = self._shape({"issues": [_issue("ABC-9", description=body)]})
        self.assertEqual(out["issues"][0]["fields"]["description"], body)

    def test_keeps_an_unknown_custom_field_verbatim(self):
        # The `fields` argument is the caller's own projection, so a custom field
        # this module has never heard of must survive untouched.
        issue = _issue("ABC-7")
        issue["fields"]["customfield_10021"] = {"value": "Squad Blue", "id": "10021"}
        out = self._shape({"issues": [issue]})
        self.assertEqual(
            out["issues"][0]["fields"]["customfield_10021"],
            {"value": "Squad Blue", "id": "10021"},
        )

    def test_keeps_what_a_caller_needs_to_page(self):
        out = self._shape(_search_response())
        self.assertEqual(out["next_page_token"], "abcdef")
        self.assertFalse(out["is_last"])
        self.assertEqual(out["total"], 2)

    def test_is_substantially_smaller(self):
        raw = json.dumps(_search_response(count=30))
        shaped = mcp_server.shape(raw, response_shaping.shape_search)
        self.assertLess(
            len(shaped), len(raw) * 0.6, "REST plumbing is ~30-40% of the payload"
        )

    def test_verbose_returns_the_raw_bytes(self):
        raw = json.dumps(_search_response())
        self.assertEqual(
            mcp_server.shape(raw, response_shaping.shape_search, verbose=True), raw
        )

    def test_unrecognized_payload_passes_through(self):
        raw = json.dumps({"warningMessages": ["bad JQL"], "errorMessages": []})
        self.assertEqual(mcp_server.shape(raw, response_shaping.shape_search), raw)

    def test_error_envelope_passes_through(self):
        raw = json.dumps(
            {"ok": False, "error": "http_status", "status_code": 400,
             "body": "invalid JQL"}
        )
        self.assertEqual(mcp_server.shape(raw, response_shaping.shape_search), raw)


class TestJiraGetIssueShaping(unittest.TestCase):
    def test_single_issue_is_stripped_the_same_way(self):
        raw = json.dumps(_issue("ABC-42"))
        out = json.loads(mcp_server.shape(raw, response_shaping.shape_issue))
        self.assertEqual(out["key"], "ABC-42")
        self.assertNotIn("self", out)
        self.assertNotIn("expand", out)
        self.assertNotIn("statusCategory", out["fields"]["status"])
        self.assertEqual(out["fields"]["status"]["name"], "Open")

    def test_a_payload_without_fields_passes_through(self):
        raw = json.dumps({"errorMessages": ["Issue does not exist"]})
        self.assertEqual(mcp_server.shape(raw, response_shaping.shape_issue), raw)


class TestJiraShapedToolCalls(unittest.TestCase):
    """The tools return the projection, and verbose=true opts out."""

    def setUp(self):
        self.env = {
            "UC_PROXY_CONNECTION_NAME": "jira-mcp",
            "UC_PROXY_PROFILE": "logfood",
        }
        uc_proxy_client.reset_workspace_client()
        self._patcher = patch("databricks.sdk.WorkspaceClient")
        self.mock_wc_class = self._patcher.start()
        self.http = MagicMock()
        self.mock_wc = MagicMock()
        self.mock_wc.serving_endpoints.http_request = self.http
        self.mock_wc_class.return_value = self.mock_wc
        self._set_body(_search_response())

    def _set_body(self, body):
        payload = json.dumps(body)
        r = MagicMock()
        r.status_code = 200
        r.text = payload
        r.json = lambda: json.loads(payload)
        r.content = payload.encode()
        self.http.return_value = r

    def tearDown(self):
        self._patcher.stop()
        uc_proxy_client.reset_workspace_client()

    def _call(self, fn, *args, **kwargs):
        with patch.dict(os.environ, self.env, clear=True):
            return fn(*args, **kwargs)

    def test_search_returns_the_projection(self):
        out = json.loads(self._call(mcp_server.jira_search, jql="project = ABC"))
        self.assertNotIn("self", out["issues"][0])
        self.assertNotIn("statusCategory", out["issues"][0]["fields"]["status"])

    def test_search_verbose_returns_the_upstream_body(self):
        out = json.loads(
            self._call(mcp_server.jira_search, jql="project = ABC", verbose=True)
        )
        self.assertIn("self", out["issues"][0])
        self.assertIn("statusCategory", out["issues"][0]["fields"]["status"])

    def test_search_still_sends_the_requested_fields(self):
        self._call(mcp_server.jira_search, jql="project = ABC", fields="summary,status")
        self.assertEqual(
            self.http.call_args.kwargs["json"]["fields"], ["summary", "status"]
        )

    def test_get_issue_returns_the_projection(self):
        self._set_body(_issue("ABC-42"))
        out = json.loads(self._call(mcp_server.jira_get_issue, key="ABC-42"))
        self.assertEqual(out["key"], "ABC-42")
        self.assertNotIn("self", out)

    def test_get_issue_verbose_returns_the_upstream_body(self):
        self._set_body(_issue("ABC-42"))
        out = json.loads(
            self._call(mcp_server.jira_get_issue, key="ABC-42", verbose=True)
        )
        self.assertIn("self", out)


if __name__ == "__main__":
    unittest.main()
