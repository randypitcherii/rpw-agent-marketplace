"""Unit tests: google_drive_get_file → UC http_request path/params shaping (TDD).

Guards the #-issue fix that `google_drive_get_file` (the `drive_file_get` tool)
forwards a BARE `fields` projection to the single-file endpoint
`drive/v3/files/{file_id}` — never a `files(...)` list-style wrapper — and returns
that single file's metadata rather than a cached listing. Fully mocked; no live
credentials or network.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod
from lib import uc_proxy_client

# Import after sys.path is set up.
import mcp_server


class TestDriveGetFileShaping(unittest.TestCase):
    """Assert the get-file tool uses the single-file path and a bare fields projection."""

    def setUp(self):
        self.env = {
            "UC_PROXY_CONNECTION_NAME": "google-mcp",
            "UC_PROXY_PROFILE": "example-profile",
        }
        uc_proxy_client.reset_workspace_client()
        self._patcher = patch("databricks.sdk.WorkspaceClient")
        self.mock_wc_class = self._patcher.start()
        self.http = MagicMock()
        self.mock_wc = MagicMock()
        self.mock_wc.serving_endpoints.http_request = self.http
        self.mock_wc_class.return_value = self.mock_wc

        # A single-file metadata body (NOT a {"files": [...]} listing).
        self._single_file = {
            "name": "budget.xlsx",
            "owners": [{"displayName": "Ada", "emailAddress": "ada@example.com"}],
            "modifiedTime": "2026-01-02T03:04:05.000Z",
        }
        r = MagicMock()
        r.status_code = 200
        r.text = json.dumps(self._single_file)
        r.json = lambda: self._single_file
        r.content = r.text.encode()
        self.http.return_value = r

    def tearDown(self):
        self._patcher.stop()
        uc_proxy_client.reset_workspace_client()

    def _call(self, *args, **kwargs):
        with patch.dict(os.environ, self.env, clear=True):
            return mcp_server.google_drive_get_file(*args, **kwargs)

    def test_forwards_bare_fields_to_single_file_endpoint(self):
        """fields="name,owners,modifiedTime" reaches files/{id} unwrapped."""
        out = self._call("FILE123", fields="name,owners,modifiedTime")
        self.http.assert_called_once()
        call = self.http.call_args
        self.assertEqual(call.kwargs["conn"], "google-mcp")
        self.assertEqual(call.kwargs["method"], ExternalFunctionRequestHttpMethod.GET)
        self.assertEqual(call.kwargs["path"], "drive/v3/files/FILE123")
        # BARE projection: exactly what the caller passed — no files(...) wrapping,
        # no allowlist mutation, no nextPageToken.
        self.assertEqual(call.kwargs["params"], {"fields": "name,owners,modifiedTime"})
        fields = call.kwargs["params"]["fields"]
        self.assertNotIn("files(", fields)
        self.assertNotIn("nextPageToken", fields)
        # Returns the single file's metadata, not a listing envelope.
        self.assertEqual(json.loads(out), self._single_file)
        self.assertNotIn("files", json.loads(out))

    def test_default_fields_is_a_bare_projection(self):
        """The default fields value is a valid bare files.get projection (no wrapping)."""
        self._call("ABC")
        params = self.http.call_args.kwargs["params"]
        self.assertNotIn("files(", params["fields"])
        self.assertNotIn("nextPageToken", params["fields"])
        # Sanity: it names real File resource fields at the top level.
        self.assertIn("name", params["fields"])

    def test_returns_single_file_not_cached_listing(self):
        """A get-file call returns one file's metadata, never a {"files": [...]} listing."""
        listing = {"files": [{"id": "x"}], "nextPageToken": "tok"}
        r = MagicMock()
        r.status_code = 200
        r.text = json.dumps(listing)
        r.json = lambda: listing
        r.content = r.text.encode()
        # Even if some upstream returned a listing, the path we hit is the
        # single-file endpoint — assert we requested files/{id}, not files.
        self.http.return_value = r
        self._call("FILE999", fields="name")
        self.assertEqual(
            self.http.call_args.kwargs["path"], "drive/v3/files/FILE999"
        )


if __name__ == "__main__":
    unittest.main()
