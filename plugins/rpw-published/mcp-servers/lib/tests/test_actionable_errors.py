"""Tests for actionable credential errors (issue #94).

Resolvers detect known failure modes (expired refresh token, missing scope,
missing field, missing gcloud ADC, etc.) and raise CredentialResolutionError
with an exact remediation command so each MCP server's run_mcp.py can surface
a single clear stderr line.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestCredentialResolutionError(unittest.TestCase):
    def test_message_and_remediation_combined(self):
        from lib.errors import CredentialResolutionError

        exc = CredentialResolutionError(
            "Auth expired for Databricks profile 'test-profile'",
            remediation="databricks auth login --profile test-profile",
            kind="databricks_auth_expired",
            context={"profile": "test-profile"},
        )
        rendered = str(exc)
        self.assertIn("Auth expired", rendered)
        self.assertIn(
            "run: databricks auth login --profile test-profile",
            rendered,
        )
        self.assertEqual(exc.kind, "databricks_auth_expired")
        self.assertEqual(exc.context, {"profile": "test-profile"})
        self.assertEqual(exc.remediation, "databricks auth login --profile test-profile")

    def test_message_only_when_no_remediation(self):
        from lib.errors import CredentialResolutionError

        exc = CredentialResolutionError("Something else")
        self.assertEqual(str(exc), "Something else")
        self.assertIsNone(exc.remediation)


class TestUcProxyExpiredAuth(unittest.TestCase):
    """uc_proxy.resolve() must detect Databricks token expiry pre-flight."""

    def _fake_run(self, returncode: int, stdout: str = "", stderr: str = ""):
        def factory(*_args, **_kwargs):
            r = mock.Mock()
            r.returncode = returncode
            r.stdout = stdout
            r.stderr = stderr
            return r

        return factory

    def test_raises_typed_error_on_invalid_refresh_token(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import uc_proxy

        # databricks auth env fails first with the well-known expired-token text.
        with mock.patch(
            "lib.resolvers.uc_proxy.subprocess.run",
            side_effect=self._fake_run(
                1, "", "Error: invalid_request: Refresh token is invalid"
            ),
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                uc_proxy.resolve(connection_name="example-mcp", databricks_profile="test-profile")

        exc = ctx.exception
        self.assertEqual(exc.kind, "databricks_auth_expired")
        self.assertIn("test-profile", exc.message)
        self.assertEqual(exc.remediation, "databricks auth login --profile test-profile")

    def test_raises_typed_error_on_generic_auth_failure(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import uc_proxy

        with mock.patch(
            "lib.resolvers.uc_proxy.subprocess.run",
            side_effect=self._fake_run(
                1, "", "Error: cannot reach workspace"
            ),
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                uc_proxy.resolve(connection_name="example-mcp", databricks_profile="test-profile")

        exc = ctx.exception
        self.assertEqual(exc.remediation, "databricks auth login --profile test-profile")
        # Generic failures still cite the profile and recommend re-login as the first move
        self.assertIn("test-profile", str(exc))

    def test_raises_typed_error_when_connection_inaccessible(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import uc_proxy

        # First call (auth env) succeeds; second (api get) fails with 403/permission denied
        env_ok = mock.Mock(returncode=0, stdout=json.dumps({"env": {"DATABRICKS_HOST": "https://x"}}), stderr="")
        conn_denied = mock.Mock(returncode=1, stdout="", stderr="PERMISSION_DENIED: User lacks USE_CONNECTION")

        with mock.patch(
            "lib.resolvers.uc_proxy.subprocess.run",
            side_effect=[conn_denied, env_ok],
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                uc_proxy.resolve(connection_name="example-mcp", databricks_profile="test-profile")

        self.assertEqual(ctx.exception.kind, "uc_connection_inaccessible")
        self.assertIn("example-mcp", ctx.exception.message)

    def test_raises_not_authorized_when_user_credential_state_missing(self):
        """USE_CONNECTION succeeds but the user has no ACTIVE OAuth credential
        — runtime calls would fail with opaque 'Session terminated', so detect
        at startup and emit the Databricks UI URL as the remediation."""
        from lib.errors import CredentialResolutionError
        from lib.resolvers import uc_proxy

        host = "https://example.cloud.databricks.com"
        conn_ok = mock.Mock(returncode=0, stdout=json.dumps({"name": "example-mcp"}), stderr="")
        me_ok = mock.Mock(returncode=0, stdout=json.dumps({"id": "u-1"}), stderr="")
        # user-credentials endpoint reports the credential is missing/expired.
        cred_missing = mock.Mock(returncode=1, stdout="", stderr="RESOURCE_DOES_NOT_EXIST")

        with mock.patch(
            "lib.resolvers.uc_proxy.databricks_auth.get_workspace_host",
            return_value=host,
        ), mock.patch(
            "lib.resolvers.uc_proxy.subprocess.run",
            side_effect=[conn_ok, me_ok, cred_missing],
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                uc_proxy.resolve(connection_name="example-mcp", databricks_profile="test-profile")

        exc = ctx.exception
        self.assertEqual(exc.kind, "uc_connection_not_authorized")
        self.assertIn("example-mcp", exc.message)
        self.assertIn(f"{host}/explore/connections/example-mcp", exc.remediation)

    def test_raises_not_authorized_when_refresh_token_is_expired(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import uc_proxy

        host = "https://example.cloud.databricks.com"
        conn_ok = mock.Mock(returncode=0, stdout=json.dumps({"name": "example-mcp"}), stderr="")
        me_ok = mock.Mock(returncode=0, stdout=json.dumps({"id": "u-1"}), stderr="")
        cred_expired = mock.Mock(
            returncode=0,
            stdout=json.dumps(
                {
                    "connection_user_credential": {
                        "options_kvpairs": {
                            "options": {
                                "refresh_token_expiration": "2000-01-01 00:00:00.000",
                            },
                        },
                        "provisioning_info": {"state": "ACTIVE"},
                    }
                }
            ),
            stderr="",
        )

        with mock.patch(
            "lib.resolvers.uc_proxy.databricks_auth.get_workspace_host",
            return_value=host,
        ), mock.patch(
            "lib.resolvers.uc_proxy.subprocess.run",
            side_effect=[conn_ok, me_ok, cred_expired],
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                uc_proxy.resolve(connection_name="example-mcp", databricks_profile="test-profile")

        exc = ctx.exception
        self.assertEqual(exc.kind, "uc_connection_not_authorized")
        self.assertIn("state=EXPIRED", exc.message)
        self.assertIn(f"{host}/explore/connections/example-mcp", exc.remediation)


class TestUcConnectionExpiredAuth(unittest.TestCase):
    def test_raises_typed_error_when_current_user_fails_with_expired_token(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import uc_connection

        fail = mock.Mock(returncode=1, stdout="", stderr="invalid_request: Refresh token is invalid")
        with mock.patch(
            "lib.resolvers.uc_connection.subprocess.run", return_value=fail
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                uc_connection.resolve(
                    connection_name="exa",
                    env_var_map={"api_key": "EXA_API_KEY"},
                    databricks_profile="test-profile",
                )

        self.assertEqual(ctx.exception.kind, "databricks_auth_expired")
        self.assertEqual(ctx.exception.remediation, "databricks auth login --profile test-profile")

    def test_raises_typed_error_when_field_missing(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import uc_connection

        # current-user me OK
        user_ok = mock.Mock(returncode=0, stdout=json.dumps({"id": "u-1"}), stderr="")
        # connection metadata OK but missing the requested field
        conn_payload = {
            "connection_user_credential": {
                "state": "ACTIVE",
                "options_kvpairs": {"options": {"other_field": "x"}},
            }
        }
        conn_ok = mock.Mock(returncode=0, stdout=json.dumps(conn_payload), stderr="")

        with mock.patch(
            "lib.resolvers.uc_connection.subprocess.run",
            side_effect=[user_ok, conn_ok],
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                uc_connection.resolve(
                    connection_name="exa",
                    env_var_map={"api_key": "EXA_API_KEY"},
                    databricks_profile="test-profile",
                )

        exc = ctx.exception
        self.assertEqual(exc.kind, "uc_connection_field_missing")
        self.assertIn("api_key", exc.message)
        self.assertIn("other_field", exc.message)  # available fields listed


class TestDatabricksSecretsActionable(unittest.TestCase):
    def test_raises_typed_error_on_expired_auth(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import databricks_secrets

        fail = mock.Mock(returncode=1, stdout="", stderr="invalid_request: Refresh token is invalid")
        with mock.patch(
            "lib.resolvers.databricks_secrets.subprocess.run", return_value=fail
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                databricks_secrets.resolve(
                    scope="myscope",
                    secret_map={"gemini_api_key": "GEMINI_API_KEY"},
                    databricks_profile="test-profile",
                )

        self.assertEqual(ctx.exception.kind, "databricks_auth_expired")
        self.assertEqual(
            ctx.exception.remediation, "databricks auth login --profile test-profile"
        )

    def test_raises_typed_error_on_missing_scope(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import databricks_secrets

        fail = mock.Mock(
            returncode=1,
            stdout="",
            stderr="RESOURCE_DOES_NOT_EXIST: Scope myscope does not exist",
        )
        with mock.patch(
            "lib.resolvers.databricks_secrets.subprocess.run", return_value=fail
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                databricks_secrets.resolve(
                    scope="myscope",
                    secret_map={"k1": "ENV1"},
                    databricks_profile="test-profile",
                )

        exc = ctx.exception
        self.assertEqual(exc.kind, "databricks_secret_scope_missing")
        self.assertIn("myscope", exc.message)
        self.assertEqual(
            exc.remediation,
            "databricks secrets create-scope myscope --profile test-profile",
        )


class TestGcloudAdcActionable(unittest.TestCase):
    def test_raises_typed_error_when_adc_missing(self):
        from lib.errors import CredentialResolutionError
        from lib.resolvers import gcloud_adc

        nonexistent = Path("/nonexistent/path/adc.json")
        with self.assertRaises(CredentialResolutionError) as ctx:
            gcloud_adc.resolve(
                env_var_map={"client_id": "GOOGLE_CLIENT_ID"}, adc_path=nonexistent
            )

        exc = ctx.exception
        self.assertEqual(exc.kind, "gcloud_adc_missing")
        self.assertEqual(
            exc.remediation, "gcloud auth application-default login"
        )


if __name__ == "__main__":
    unittest.main()
