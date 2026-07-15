"""Tests for the Databricks profile/auth wrapper (issue #297).

All SDK/CLI seams are mocked — no live Databricks calls, no browser flow, no
secrets touched. Covers: valid profile, missing profile, expired auth, CLI
unavailable, non-interactive mode, and browser-login invocation.
"""

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

# Allow imports from the parent mcp-servers directory (mirrors sibling tests).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from lib import databricks_auth  # noqa: E402
from lib.errors import CredentialResolutionError  # noqa: E402


def _fake_client(user_name="alice@example.com", host="https://ws.cloud.databricks.com"):
    client = mock.Mock()
    client.config = mock.Mock(host=host)
    me = mock.Mock()
    me.user_name = user_name
    me.id = "u-1"
    client.current_user.me.return_value = me
    return client


class TestValidateProfile(unittest.TestCase):
    def test_valid_profile_returns_active(self):
        with mock.patch.object(
            databricks_auth, "_build_workspace_client", return_value=_fake_client()
        ):
            status = databricks_auth.validate_profile("prod")

        self.assertTrue(status.authenticated)
        self.assertTrue(status.ok)
        self.assertEqual(status.state, databricks_auth.STATE_ACTIVE)
        self.assertEqual(status.user, "alice@example.com")
        self.assertEqual(status.host, "https://ws.cloud.databricks.com")
        self.assertIsNone(status.error)

    def test_missing_profile_is_classified(self):
        exc = ValueError(
            "resolve: /Users/x/.databrickscfg has no prod profile configured"
        )
        with mock.patch.object(
            databricks_auth, "_build_workspace_client", side_effect=exc
        ):
            status = databricks_auth.validate_profile("prod")

        self.assertFalse(status.authenticated)
        self.assertEqual(status.state, databricks_auth.STATE_MISSING_PROFILE)
        self.assertEqual(status.error.kind, "databricks_profile_missing")
        self.assertEqual(
            status.error.remediation, "databricks auth login --profile prod"
        )

    def test_expired_auth_is_classified(self):
        client = mock.Mock()
        client.config = mock.Mock(host="https://ws.cloud.databricks.com")
        client.current_user.me.side_effect = Exception(
            "default auth: Refresh token is invalid"
        )
        with mock.patch.object(
            databricks_auth, "_build_workspace_client", return_value=client
        ):
            status = databricks_auth.validate_profile("prod")

        self.assertFalse(status.authenticated)
        self.assertEqual(status.state, databricks_auth.STATE_EXPIRED)
        self.assertEqual(status.error.kind, "databricks_auth_expired")
        # Host still surfaced from the constructed client even though me() failed.
        self.assertEqual(status.host, "https://ws.cloud.databricks.com")

    def test_unknown_auth_failure_is_unauthenticated(self):
        client = mock.Mock()
        client.config = mock.Mock(host="")
        client.current_user.me.side_effect = Exception("cannot reach workspace")
        with mock.patch.object(
            databricks_auth, "_build_workspace_client", return_value=client
        ):
            status = databricks_auth.validate_profile("prod")

        self.assertFalse(status.authenticated)
        self.assertEqual(status.state, databricks_auth.STATE_UNAUTHENTICATED)
        self.assertEqual(status.error.kind, "databricks_auth_error")


class TestGetWorkspaceHost(unittest.TestCase):
    def test_returns_host_stripped(self):
        with mock.patch.object(
            databricks_auth,
            "_build_config",
            return_value=mock.Mock(host="https://ws.cloud.databricks.com/"),
        ):
            self.assertEqual(
                databricks_auth.get_workspace_host("prod"),
                "https://ws.cloud.databricks.com",
            )

    def test_missing_profile_raises_typed_error(self):
        exc = ValueError("has no prod profile configured")
        with mock.patch.object(databricks_auth, "_build_config", side_effect=exc):
            with self.assertRaises(CredentialResolutionError) as ctx:
                databricks_auth.get_workspace_host("prod")
        self.assertEqual(ctx.exception.kind, "databricks_profile_missing")

    def test_no_host_raises_typed_error(self):
        with mock.patch.object(
            databricks_auth, "_build_config", return_value=mock.Mock(host="")
        ):
            with self.assertRaises(CredentialResolutionError) as ctx:
                databricks_auth.get_workspace_host("prod")
        self.assertEqual(ctx.exception.kind, "databricks_auth_error")


class TestClassifyCliError(unittest.TestCase):
    def test_expired(self):
        err = databricks_auth.classify_cli_error("prod", "invalid_grant: token revoked")
        self.assertEqual(err.kind, "databricks_auth_expired")

    def test_missing_profile(self):
        err = databricks_auth.classify_cli_error("prod", "no such profile")
        self.assertEqual(err.kind, "databricks_profile_missing")

    def test_fallback_used_for_unrelated_error(self):
        fallback = CredentialResolutionError("boom", kind="uc_connection_inaccessible")
        err = databricks_auth.classify_cli_error(
            "prod", "PERMISSION_DENIED", fallback=fallback
        )
        self.assertIs(err, fallback)

    def test_generic_when_no_fallback(self):
        err = databricks_auth.classify_cli_error("prod", "weird failure")
        self.assertEqual(err.kind, "databricks_auth_error")


class TestLaunchProfileLogin(unittest.TestCase):
    def test_cli_unavailable_returns_typed_error(self):
        with mock.patch.object(databricks_auth, "_databricks_cli_path", return_value=None):
            status = databricks_auth.launch_profile_login("prod")

        self.assertFalse(status.authenticated)
        self.assertEqual(status.state, databricks_auth.STATE_CLI_UNAVAILABLE)
        self.assertEqual(status.error.kind, "databricks_cli_unavailable")

    def test_success_revalidates(self):
        run_ok = mock.Mock(returncode=0)
        active = databricks_auth.AuthStatus(
            profile="prod", authenticated=True, state=databricks_auth.STATE_ACTIVE
        )
        with mock.patch.object(
            databricks_auth, "_databricks_cli_path", return_value="/usr/bin/databricks"
        ), mock.patch.object(
            databricks_auth.subprocess, "run", return_value=run_ok
        ) as run, mock.patch.object(
            databricks_auth, "validate_profile", return_value=active
        ):
            status = databricks_auth.launch_profile_login("prod", host="https://ws")

        self.assertTrue(status.authenticated)
        # Command shape: uses discovered CLI, targets the profile + host, no capture.
        cmd = run.call_args.args[0]
        self.assertEqual(
            cmd,
            ["/usr/bin/databricks", "auth", "login", "--profile", "prod", "--host", "https://ws"],
        )
        # stdin is redirected away so a stray prompt can't hang the flow.
        self.assertIn("stdin", run.call_args.kwargs)

    def test_nonzero_exit_returns_login_failed(self):
        run_fail = mock.Mock(returncode=1)
        with mock.patch.object(
            databricks_auth, "_databricks_cli_path", return_value="/usr/bin/databricks"
        ), mock.patch.object(databricks_auth.subprocess, "run", return_value=run_fail):
            status = databricks_auth.launch_profile_login("prod")

        self.assertFalse(status.authenticated)
        self.assertEqual(status.state, databricks_auth.STATE_LOGIN_FAILED)
        self.assertEqual(status.error.kind, "databricks_auth_error")

    def test_timeout_returns_login_failed(self):
        with mock.patch.object(
            databricks_auth, "_databricks_cli_path", return_value="/usr/bin/databricks"
        ), mock.patch.object(
            databricks_auth.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="databricks", timeout=1),
        ):
            status = databricks_auth.launch_profile_login("prod")

        self.assertFalse(status.authenticated)
        self.assertEqual(status.state, databricks_auth.STATE_LOGIN_FAILED)


class TestEnsureProfileAuthenticated(unittest.TestCase):
    def test_already_authenticated_short_circuits(self):
        active = databricks_auth.AuthStatus(
            profile="prod", authenticated=True, state=databricks_auth.STATE_ACTIVE
        )
        with mock.patch.object(
            databricks_auth, "validate_profile", return_value=active
        ), mock.patch.object(databricks_auth, "launch_profile_login") as launch:
            status = databricks_auth.ensure_profile_authenticated("prod", interactive=True)

        self.assertTrue(status.authenticated)
        launch.assert_not_called()

    def test_non_interactive_returns_structured_error(self):
        expired = databricks_auth.AuthStatus(
            profile="prod",
            authenticated=False,
            state=databricks_auth.STATE_EXPIRED,
            error=CredentialResolutionError(
                "Auth expired for Databricks profile 'prod'",
                kind="databricks_auth_expired",
            ),
        )
        with mock.patch.object(
            databricks_auth, "validate_profile", return_value=expired
        ), mock.patch.object(databricks_auth, "launch_profile_login") as launch:
            status = databricks_auth.ensure_profile_authenticated("prod", interactive=False)

        launch.assert_not_called()
        self.assertFalse(status.authenticated)
        self.assertEqual(status.state, databricks_auth.STATE_NON_INTERACTIVE)
        self.assertEqual(status.error.kind, "databricks_auth_non_interactive")
        # The underlying auth state is preserved for callers that want it.
        self.assertEqual(status.error.context.get("underlying_kind"), "databricks_auth_expired")
        # Remediation names the interactive command, not an impossible headless retry.
        self.assertIn("databricks auth login --profile prod", status.error.remediation)

    def test_interactive_launches_login_with_host(self):
        expired = databricks_auth.AuthStatus(
            profile="prod",
            authenticated=False,
            state=databricks_auth.STATE_EXPIRED,
            host="https://ws.cloud.databricks.com",
        )
        recovered = databricks_auth.AuthStatus(
            profile="prod", authenticated=True, state=databricks_auth.STATE_ACTIVE
        )
        with mock.patch.object(
            databricks_auth, "validate_profile", return_value=expired
        ), mock.patch.object(
            databricks_auth, "launch_profile_login", return_value=recovered
        ) as launch:
            status = databricks_auth.ensure_profile_authenticated("prod", interactive=True)

        self.assertTrue(status.authenticated)
        launch.assert_called_once_with("prod", host="https://ws.cloud.databricks.com")


class TestAuthStatus(unittest.TestCase):
    def test_raise_if_unauthenticated(self):
        err = CredentialResolutionError("nope", kind="databricks_auth_expired")
        status = databricks_auth.AuthStatus(
            profile="prod", authenticated=False,
            state=databricks_auth.STATE_EXPIRED, error=err,
        )
        with self.assertRaises(CredentialResolutionError):
            status.raise_if_unauthenticated()

    def test_as_dict_includes_error_envelope(self):
        err = CredentialResolutionError(
            "nope", kind="databricks_auth_expired",
            remediation="databricks auth login --profile prod",
        )
        status = databricks_auth.AuthStatus(
            profile="prod", authenticated=False,
            state=databricks_auth.STATE_EXPIRED, host="https://ws", error=err,
        )
        d = status.as_dict()
        self.assertEqual(d["state"], databricks_auth.STATE_EXPIRED)
        self.assertEqual(d["error"]["kind"], "databricks_auth_expired")
        self.assertEqual(d["host"], "https://ws")


if __name__ == "__main__":
    unittest.main()
