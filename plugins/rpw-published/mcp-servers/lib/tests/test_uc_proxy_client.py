"""Tests for the shared UC-proxy client helpers."""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod

from lib import uc_proxy_client


class TestRequireProxyEnv(unittest.TestCase):
    def test_raises_when_both_unset(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                uc_proxy_client.require_proxy_env()
        self.assertIn("UC_PROXY_CONNECTION_NAME", str(ctx.exception))
        self.assertIn("UC_PROXY_PROFILE", str(ctx.exception))

    def test_raises_when_connection_missing(self):
        with patch.dict(os.environ, {"UC_PROXY_PROFILE": "test-profile"}, clear=True):
            with self.assertRaises(RuntimeError):
                uc_proxy_client.require_proxy_env()

    def test_raises_when_profile_missing(self):
        with patch.dict(
            os.environ, {"UC_PROXY_CONNECTION_NAME": "google-mcp"}, clear=True
        ):
            with self.assertRaises(RuntimeError):
                uc_proxy_client.require_proxy_env()

    def test_raises_when_values_are_whitespace(self):
        with patch.dict(
            os.environ,
            {"UC_PROXY_CONNECTION_NAME": "  ", "UC_PROXY_PROFILE": "\t"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                uc_proxy_client.require_proxy_env()

    def test_returns_pair_when_set(self):
        with patch.dict(
            os.environ,
            {
                "UC_PROXY_CONNECTION_NAME": "google-mcp",
                "UC_PROXY_PROFILE": "test-profile",
            },
            clear=True,
        ):
            conn, profile = uc_proxy_client.require_proxy_env()
        self.assertEqual(conn, "google-mcp")
        self.assertEqual(profile, "test-profile")

    def test_strips_whitespace_from_values(self):
        with patch.dict(
            os.environ,
            {
                "UC_PROXY_CONNECTION_NAME": "  google-mcp  ",
                "UC_PROXY_PROFILE": "  test-profile\n",
            },
            clear=True,
        ):
            conn, profile = uc_proxy_client.require_proxy_env()
        self.assertEqual(conn, "google-mcp")
        self.assertEqual(profile, "test-profile")


def _mock_workspace_client_returning(response):
    ws = MagicMock()
    ws.serving_endpoints.http_request.return_value = response
    return ws


class TestRequest(unittest.TestCase):
    def setUp(self):
        self.response = MagicMock()
        self.response.status_code = 200
        self.response.text = '{"foo": "bar"}'
        self.response.json = lambda: {"foo": "bar"}
        self.response.content = b'{"foo": "bar"}'
        self.ws = _mock_workspace_client_returning(self.response)

    def test_happy_path_builds_correct_call_and_returns_json(self):
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="google-mcp",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="drive/v3/about",
            query_params={"fields": "user"},
        )
        call = self.ws.serving_endpoints.http_request.call_args.kwargs
        self.assertEqual(call["conn"], "google-mcp")
        self.assertEqual(call["method"], ExternalFunctionRequestHttpMethod.GET)
        self.assertEqual(call["path"], "drive/v3/about")
        self.assertEqual(
            call["headers"],
            {"Accept": "application/json", "Content-Type": "application/json"},
        )
        self.assertEqual(call["params"], {"fields": "user"})
        self.assertIsNone(call["json"])
        self.assertEqual(json.loads(out), {"foo": "bar"})

    def test_lstrips_leading_slash_in_path(self):
        uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="/drive/v3/files",
        )
        self.assertEqual(
            self.ws.serving_endpoints.http_request.call_args.kwargs["path"],
            "drive/v3/files",
        )

    def test_http_4xx_returns_structured_error(self):
        self.response.status_code = 404
        self.response.text = "Not Found"
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        data = json.loads(out)
        self.assertEqual(data["ok"], False)
        self.assertEqual(data["error"], "http_status")
        self.assertEqual(data["status_code"], 404)
        self.assertEqual(data["body"], "Not Found")

    def test_http_5xx_returns_structured_error(self):
        self.response.status_code = 502
        self.response.text = "Bad Gateway"
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        data = json.loads(out)
        self.assertEqual(data["error"], "http_status")
        self.assertEqual(data["status_code"], 502)

    def test_invalid_json_returns_structured_error(self):
        self.response.status_code = 200
        self.response.text = "<html>oops</html>"
        self.response.content = b"<html>oops</html>"

        def boom():
            raise ValueError("not json")

        self.response.json = boom
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        data = json.loads(out)
        self.assertEqual(data["ok"], False)
        self.assertEqual(data["error"], "invalid_json")
        self.assertEqual(data["raw"], "<html>oops</html>")

    def test_empty_body_returns_ok_null_data(self):
        self.response.status_code = 200
        self.response.content = b""
        self.response.text = ""
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        self.assertEqual(json.loads(out), {"ok": True, "data": None})

    def test_non_dict_json_wrapped_in_data_envelope(self):
        self.response.json = lambda: [1, 2, 3]
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        self.assertEqual(json.loads(out), {"ok": True, "data": [1, 2, 3]})

    def test_sdk_exception_returns_string_error(self):
        self.ws.serving_endpoints.http_request.side_effect = RuntimeError(
            "uc denied"
        )
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        data = json.loads(out)
        self.assertEqual(data["ok"], False)
        self.assertIn("uc denied", data["error"])

    def test_truncates_oversized_bodies(self):
        big = "x" * 5000
        self.response.status_code = 500
        self.response.text = big
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        data = json.loads(out)
        self.assertEqual(len(data["body"]), 2000)

    def test_json_body_passed_through(self):
        uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.POST,
            path="thing",
            json_body={"hello": "world"},
        )
        call = self.ws.serving_endpoints.http_request.call_args.kwargs
        self.assertEqual(call["json"], {"hello": "world"})


class TestUcOAuthFailures(unittest.TestCase):
    def setUp(self):
        self.response = MagicMock()
        self.response.status_code = 401
        self.response.content = b""
        self.response.text = (
            "The OAuth token exchange failed with HTTP status code 401 Unauthorized. "
            "The returned server response or exception message is: "
            "Map(error -> invalid_client, error_description -> Client authentication failed)"
        )
        self.ws = _mock_workspace_client_returning(self.response)

    def test_invalid_client_401_returns_reauthentication_envelope(self):
        with patch.dict(
            os.environ,
            {
                "UC_PROXY_PROFILE": "test-profile",
                "UC_PROXY_URL": (
                    "https://adb-1111222233334444.5.azuredatabricks.net/"
                    "api/2.0/unity-catalog/connections/system_ai_agent_example_mcp/proxy/"
                ),
            },
            clear=True,
        ):
            out = uc_proxy_client.request(
                workspace_client=self.ws,
                conn="system_ai_agent_example_mcp",
                method=ExternalFunctionRequestHttpMethod.POST,
                path="search",
            )

        data = json.loads(out)
        self.assertEqual(data["ok"], False)
        self.assertEqual(data["error"], "uc_oauth_reauthentication_required")
        self.assertEqual(data["status_code"], 401)
        self.assertEqual(data["connection_name"], "system_ai_agent_example_mcp")
        self.assertEqual(data["profile"], "test-profile")
        self.assertEqual(
            data["reauth_url"],
            "https://adb-1111222233334444.5.azuredatabricks.net/"
            "explore/connections/system_ai_agent_example_mcp",
        )
        self.assertTrue(data["retryable_after_reauth"])
        self.assertIn("needs to be reauthenticated", data["remediation"])

    def test_oauth_token_exchange_exception_returns_reauthentication_envelope(self):
        self.ws.serving_endpoints.http_request.side_effect = RuntimeError(
            "Failed request to https://acme-be.example-search.com:443/rest/api/v1/search. "
            "Error: The OAuth token exchange failed with HTTP status code 401 Unauthorized. "
            "The returned server response or exception message is: Map(error -> invalid_grant)"
        )
        with patch.dict(
            os.environ,
            {
                "UC_PROXY_PROFILE": "test-profile",
                "UC_PROXY_URL": (
                    "https://adb-1111222233334444.5.azuredatabricks.net/"
                    "api/2.0/unity-catalog/connections/system_ai_agent_example_mcp/proxy/"
                ),
            },
            clear=True,
        ):
            out = uc_proxy_client.request(
                workspace_client=self.ws,
                conn="system_ai_agent_example_mcp",
                method=ExternalFunctionRequestHttpMethod.POST,
                path="search",
            )

        data = json.loads(out)
        self.assertEqual(data["error"], "uc_oauth_reauthentication_required")
        self.assertEqual(data["connection_name"], "system_ai_agent_example_mcp")
        self.assertIn("invalid_grant", data["body"])

    def test_unrelated_401_stays_http_status(self):
        self.response.text = "401 Unauthorized: missing upstream permission"
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="google-mcp",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="drive/v3/files",
        )

        data = json.loads(out)
        self.assertEqual(data["error"], "http_status")
        self.assertEqual(data["status_code"], 401)


class TestGetWorkspaceClient(unittest.TestCase):
    def setUp(self):
        uc_proxy_client.reset_workspace_client()

    def tearDown(self):
        uc_proxy_client.reset_workspace_client()

    def test_cache_hit_returns_same_instance(self):
        """Two consecutive calls return the same object; constructor called once."""
        sentinel = MagicMock()
        with patch("databricks.sdk.WorkspaceClient", return_value=sentinel) as mock_ws:
            c1 = uc_proxy_client.get_workspace_client("test-profile")
            c2 = uc_proxy_client.get_workspace_client("test-profile")
        self.assertIs(c1, c2)
        mock_ws.assert_called_once_with(profile="test-profile")

    def test_reset_clears_cache(self):
        """After reset_workspace_client(), the next call constructs a new instance."""
        first = MagicMock()
        second = MagicMock()
        with patch("databricks.sdk.WorkspaceClient", side_effect=[first, second]) as mock_ws:
            c1 = uc_proxy_client.get_workspace_client("test-profile")
            uc_proxy_client.reset_workspace_client()
            c2 = uc_proxy_client.get_workspace_client("test-profile")
        self.assertIs(c1, first)
        self.assertIs(c2, second)
        self.assertEqual(mock_ws.call_count, 2)

    def test_constructs_with_profile_kwarg(self):
        """WorkspaceClient is constructed with profile=<profile>."""
        sentinel = MagicMock()
        with patch("databricks.sdk.WorkspaceClient", return_value=sentinel) as mock_ws:
            uc_proxy_client.get_workspace_client("my-profile")
        mock_ws.assert_called_once_with(profile="my-profile")


class TestRequestViaEnv(unittest.TestCase):
    def setUp(self):
        uc_proxy_client.reset_workspace_client()

    def tearDown(self):
        uc_proxy_client.reset_workspace_client()

    def test_missing_env_returns_json_envelope(self):
        """When env vars are unset, returns the exact missing_env JSON envelope."""
        with patch.dict(os.environ, {}, clear=True):
            out = uc_proxy_client.request_via_env(
                ExternalFunctionRequestHttpMethod.GET,
                "some/path",
            )
        self.assertEqual(
            json.loads(out),
            {
                "ok": False,
                "error": "missing_env",
                "detail": "UC_PROXY_CONNECTION_NAME and UC_PROXY_PROFILE must be set",
            },
        )

    def test_missing_env_envelope_key_order(self):
        """The envelope JSON string preserves ok/error/detail key order."""
        with patch.dict(os.environ, {}, clear=True):
            out = uc_proxy_client.request_via_env(
                ExternalFunctionRequestHttpMethod.GET,
                "some/path",
            )
        # Check key order is ok, error, detail (matches original servers verbatim)
        keys = list(json.loads(out).keys())
        self.assertEqual(keys, ["ok", "error", "detail"])

    def test_with_env_set_calls_request_with_resolved_args(self):
        """With env set, constructs WorkspaceClient with resolved profile and calls request()."""
        fake_ws = MagicMock()
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b'{"result": "ok"}'
        fake_response.json = lambda: {"result": "ok"}
        fake_ws.serving_endpoints.http_request.return_value = fake_response

        env = {
            "UC_PROXY_CONNECTION_NAME": "google-mcp",
            "UC_PROXY_PROFILE": "test-profile",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("databricks.sdk.WorkspaceClient", return_value=fake_ws):
                out = uc_proxy_client.request_via_env(
                    ExternalFunctionRequestHttpMethod.GET,
                    "drive/v3/about",
                    query_params={"fields": "user"},
                )

        self.assertEqual(json.loads(out), {"result": "ok"})
        call_kwargs = fake_ws.serving_endpoints.http_request.call_args.kwargs
        self.assertEqual(call_kwargs["conn"], "google-mcp")
        self.assertEqual(call_kwargs["path"], "drive/v3/about")

    def test_with_env_set_passes_json_body(self):
        """json_body kwarg is forwarded to request()."""
        fake_ws = MagicMock()
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b'{"id": "evt123"}'
        fake_response.json = lambda: {"id": "evt123"}
        fake_ws.serving_endpoints.http_request.return_value = fake_response

        env = {
            "UC_PROXY_CONNECTION_NAME": "google-mcp",
            "UC_PROXY_PROFILE": "test-profile",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("databricks.sdk.WorkspaceClient", return_value=fake_ws):
                out = uc_proxy_client.request_via_env(
                    ExternalFunctionRequestHttpMethod.POST,
                    "calendar/v3/calendars/primary/events",
                    json_body={"summary": "Test"},
                )

        call_kwargs = fake_ws.serving_endpoints.http_request.call_args.kwargs
        self.assertEqual(call_kwargs["json"], {"summary": "Test"})
        self.assertEqual(json.loads(out), {"id": "evt123"})


class TestRequestHeaders(unittest.TestCase):
    """Tests for the headers= kwarg on request() and request_via_env()."""

    def setUp(self):
        self.response = MagicMock()
        self.response.status_code = 200
        self.response.text = '{"foo": "bar"}'
        self.response.json = lambda: {"foo": "bar"}
        self.response.content = b'{"foo": "bar"}'
        self.ws = _mock_workspace_client_returning(self.response)

    def test_default_headers_are_accept_and_content_type(self):
        """headers=None uses Accept+Content-Type application/json defaults."""
        uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        call = self.ws.serving_endpoints.http_request.call_args.kwargs
        self.assertEqual(
            call["headers"],
            {"Accept": "application/json", "Content-Type": "application/json"},
        )

    def test_custom_headers_replaces_defaults_no_content_type(self):
        """headers={"Accept": "application/json"} passes exactly that dict — no Content-Type."""
        uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
            headers={"Accept": "application/json"},
        )
        call = self.ws.serving_endpoints.http_request.call_args.kwargs
        self.assertEqual(call["headers"], {"Accept": "application/json"})

    def test_custom_headers_with_extra_field_passed_verbatim(self):
        """headers with X-Glean-Auth-Type is passed through verbatim."""
        custom = {"Accept": "application/json", "X-Glean-Auth-Type": "OAUTH"}
        uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
            headers=custom,
        )
        call = self.ws.serving_endpoints.http_request.call_args.kwargs
        self.assertEqual(call["headers"], custom)


class TestTreatEmptyAsError(unittest.TestCase):
    """Tests for the treat_empty_as_error= kwarg on request()."""

    def setUp(self):
        self.response = MagicMock()
        self.response.status_code = 200
        self.response.content = b""
        self.response.text = ""
        self.ws = _mock_workspace_client_returning(self.response)

    def test_empty_body_default_returns_ok_null_data(self):
        """treat_empty_as_error=False (default) returns {"ok": true, "data": null}."""
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
        )
        self.assertEqual(json.loads(out), {"ok": True, "data": None})

    def test_empty_body_treat_empty_as_error_true_returns_error(self):
        """treat_empty_as_error=True with empty body returns {"ok": false, "error": "empty_response"}."""
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
            treat_empty_as_error=True,
        )
        self.assertEqual(json.loads(out), {"ok": False, "error": "empty_response"})

    def test_non_empty_body_treat_empty_as_error_true_returns_data(self):
        """treat_empty_as_error=True with a real body still returns the data normally."""
        self.response.content = b'{"ok": true}'
        self.response.json = lambda: {"ok": True}
        out = uc_proxy_client.request(
            workspace_client=self.ws,
            conn="c",
            method=ExternalFunctionRequestHttpMethod.GET,
            path="x",
            treat_empty_as_error=True,
        )
        self.assertEqual(json.loads(out), {"ok": True})


class TestRequestViaEnvForwardsKwargs(unittest.TestCase):
    """Tests that request_via_env forwards headers= and treat_empty_as_error= to request()."""

    def setUp(self):
        uc_proxy_client.reset_workspace_client()

    def tearDown(self):
        uc_proxy_client.reset_workspace_client()

    def test_request_via_env_forwards_headers_and_treat_empty_as_error(self):
        """Both kwargs are forwarded through request_via_env to http_request."""
        fake_ws = MagicMock()
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b""
        fake_response.text = ""
        fake_ws.serving_endpoints.http_request.return_value = fake_response

        env = {
            "UC_PROXY_CONNECTION_NAME": "slack",
            "UC_PROXY_PROFILE": "test-profile",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch("databricks.sdk.WorkspaceClient", return_value=fake_ws):
                out = uc_proxy_client.request_via_env(
                    ExternalFunctionRequestHttpMethod.GET,
                    "auth.test",
                    headers={"Accept": "application/json"},
                    treat_empty_as_error=True,
                )

        # With treat_empty_as_error=True and empty body, should return error
        self.assertEqual(json.loads(out), {"ok": False, "error": "empty_response"})
        # With headers={"Accept": "application/json"}, no Content-Type should be injected
        call_kwargs = fake_ws.serving_endpoints.http_request.call_args.kwargs
        self.assertEqual(call_kwargs["headers"], {"Accept": "application/json"})


if __name__ == "__main__":
    unittest.main()
