"""Probe, wake, or nudge Omnigent sessions in one authenticated, replica-routed pass.

Run this helper through UV; it deliberately is not a direct executable:

    uv run --no-project --with 'omnigent[databricks]' python fleet_action.py \
      --server "$BASE" probe conv_123=host_9
    uv run --no-project --with 'omnigent[databricks]' python fleet_action.py \
      --server "$BASE" nudge conv_123=host_9

Remote targets are ``SESSION_ID=HOST_ID`` pairs. Three pieces of raw-REST
knowledge are folded in here so no pass re-derives them by hand (#1825):

1. **Slice key, or every session on the host 400s.** Any session-scoped call
   (``GET``/``POST /v1/sessions/{id}/…``) needs
   ``X-Databricks-Omnigent-Slice-Key: <host_id with the "host_" prefix stripped>``.
   Without it the server answers ``wrong_replica`` for *every* session on that
   host. It is deterministic, not transient — **retrying never helps**, which is
   the trap. This module builds that value itself (``slice_key``) and normalises
   a prefixed one, so the header is right even if the upstream builder omits it.
2. **``probe`` before you conclude "dead".** ``GET /v1/sessions/{id}`` exposes
   ``labels.omnigent.last_task_error_code`` (e.g. ``runner_disconnected``). That
   one read separates *genuinely dead, relaunch* from *routing-blocked, just
   re-send* — do it before any recovery action. ``probe`` mutates nothing.
3. **``session_not_a_sub_agent`` is not a lie.** ``sys_session_close`` refuses a
   child whose ``get_info.parent_session_id`` visibly matches its parent, because
   sub-agent tracking is keyed by ``(agent, title)`` under the parent, not by that
   field. See ``references/raw-rest-recovery.md`` for the discriminator.

Refusing an unkeyed remote target is intentional: sending it to the default
replica returns ``wrong_replica``.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

DEFAULT_MESSAGES = {
    "wake-stuck": (
        "Wake up and begin the task already in this session. Report your first "
        "concrete step after you start."
    ),
    "nudge": (
        "Status check: report what you have done, what is blocking you, and your "
        "next step. If your brief is finished, include the artifact (PR URL / commit)."
    ),
}

#: Every action this helper offers. ``probe`` is a read: it issues one GET and
#: mutates nothing, which is why it carries no message and needs no confirmation.
ACTIONS: tuple[str, ...] = ("probe", *sorted(DEFAULT_MESSAGES))
MUTATING_ACTIONS = frozenset(DEFAULT_MESSAGES)

#: The replica-routing header. Missing it is the single most common raw-REST
#: failure against a host-sharded server (#1825) — and it fails deterministically.
SLICE_KEY_HEADER = "X-Databricks-Omnigent-Slice-Key"

#: The label carrying why a session's last task stopped. Absent = no task error.
ERROR_CODE_LABEL = "omnigent.last_task_error_code"

#: The one error code that means the runner process is gone: a nudge cannot reach
#: it, so relaunch in place (same brief, same worktree) instead of re-sending.
RUNNER_GONE_CODES = frozenset({"runner_disconnected"})


class ActionError(RuntimeError):
    """A fleet action could not be performed safely."""


def slice_key(host_id: str | None) -> str | None:
    """The replica slice value for *host_id*: the id **without** its ``host_`` prefix.

    Measured 2026-09-17 (#1825): ``host_9`` in this header is rejected;
    ``9`` routes. Stripping is the whole fix, and it is deterministic — a call
    that 400s ``wrong_replica`` will 400 forever until the key is right.
    """
    if not host_id:
        return None
    return host_id.strip().removeprefix("host_").strip() or None


@dataclass(frozen=True)
class Target:
    session_id: str
    host_id: str | None


def is_remote(server: str) -> bool:
    """Return whether *server* needs authenticated remote handling."""
    parsed = urllib.parse.urlsplit(server)
    return parsed.hostname not in {"127.0.0.1", "localhost", "::1"}


def parse_targets(values: list[str], *, remote: bool) -> list[Target]:
    """Parse ``SESSION_ID[=HOST_ID]`` values and fail closed for remote calls."""
    targets: list[Target] = []
    seen: set[str] = set()
    for raw in values:
        session_id, separator, host_id = raw.partition("=")
        session_id = session_id.strip()
        host_id = host_id.strip() if separator else ""
        if not session_id or (separator and not host_id):
            raise ActionError(f"invalid target {raw!r}; use SESSION_ID=HOST_ID")
        if remote and not host_id:
            raise ActionError(
                f"remote target {session_id!r} has no replica route; use "
                "SESSION_ID=HOST_ID from sys_session_get_info. An unkeyed POST can "
                "fail with wrong_replica."
            )
        if session_id in seen:
            raise ActionError(f"duplicate target {session_id!r}")
        seen.add(session_id)
        targets.append(Target(session_id, host_id or None))
    return targets


def requires_confirmation(action: str) -> bool:
    """Every mutating action needs a confirmed row list first.

    `wake-stuck` is the one *mutation* exempt from the gate, and only because a
    classifier-proven stuck session has never started. `probe` is not exempt —
    it is not a mutation at all: one GET, nothing written.
    """
    return action in MUTATING_ACTIONS and action != "wake-stuck"


def _databricks_bearer(workspace_host: str, profile: str | None) -> str:
    """Mint a bearer through the public Databricks SDK authentication interface."""
    try:
        from databricks.sdk.config import Config

        config = (
            Config(profile=profile)
            if profile
            else Config(host=workspace_host, auth_type="databricks-cli")
        )
        headers = config.authenticate() or {}
        authorization = headers.get("Authorization", "")
    except Exception as exc:
        hint = (
            f"databricks auth login --profile {profile}"
            if profile
            else f"databricks auth login --host {workspace_host}"
        )
        raise ActionError(
            f"Databricks authentication failed for {workspace_host}; run `{hint}` "
            "and retry (pass --profile when the host has a named profile)"
        ) from exc
    if not authorization.startswith("Bearer ") or not authorization.removeprefix("Bearer ").strip():
        raise ActionError(
            f"Databricks authentication for {workspace_host} returned no bearer token"
        )
    return authorization.removeprefix("Bearer ").strip()


def make_header_factory(
    server: str, profile: str | None = None
) -> Callable[[str | None], dict[str, str]]:
    """Resolve Omnigent login state and return per-host request headers."""
    if not is_remote(server):
        return lambda _host_id: {"Content-Type": "application/json", "Accept": "application/json"}

    try:
        from omnigent.cli_auth import (
            databricks_request_headers,
            load_databricks_workspace_host,
            load_token,
            refresh_stored_token,
        )
    except ImportError as exc:
        raise ActionError(
            "Omnigent authentication support is unavailable; run this helper with "
            "`uv run --no-project --with 'omnigent[databricks]' python ...`"
        ) from exc

    token = load_token(server) or refresh_stored_token(server)
    if token is None:
        workspace_host = load_databricks_workspace_host(server)
        if workspace_host is None and profile is None:
            raise ActionError(
                f"no Omnigent login is configured for {server}; run "
                f"`omnigent login {server}` and retry"
            )
        token = _databricks_bearer(workspace_host or server, profile)

    def headers(host_id: str | None) -> dict[str, str]:
        routed = databricks_request_headers(
            server, bearer_token=token, host_id=host_id
        )
        if not routed.get("Authorization"):
            raise ActionError(
                f"authentication headers could not be established for {server}; "
                f"run `omnigent login {server}` and retry"
            )
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            **with_slice_key(routed, host_id),
        }

    return headers


def with_slice_key(headers: dict[str, str], host_id: str | None) -> dict[str, str]:
    """Guarantee the replica slice header, prefix-stripped, when we know the host.

    Two cases, both measured against a host-sharded server (#1825): the upstream
    builder omitted the header (add it), or it set the raw ``host_…`` id
    (normalise it). Either way an unkeyed or prefixed value 400s ``wrong_replica``
    for every session on that host, forever — so this is corrected, never retried.
    A value in some other shape is left alone; we only own the prefix.
    """
    key = slice_key(host_id)
    if key is None:
        return dict(headers)
    merged = dict(headers)
    existing = next(
        (name for name in merged if name.lower() == SLICE_KEY_HEADER.lower()), None
    )
    if existing is None:
        merged[SLICE_KEY_HEADER] = key
    elif merged[existing].strip().startswith("host_"):
        merged[existing] = key
    return merged


def _http_error(session_id: str, method: str, exc: urllib.error.HTTPError) -> ActionError:
    """Turn an HTTP failure into an actionable ActionError. Never suggests a retry."""
    detail = exc.read().decode(errors="replace")[:500]
    if "wrong_replica" in detail:
        hint = (
            f"the call reached the wrong replica. This is deterministic — retrying "
            f"never helps. Set {SLICE_KEY_HEADER} to the session's host_id with the "
            "'host_' prefix stripped (pass SESSION_ID=HOST_ID from "
            "sys_session_get_info and this helper builds it)."
        )
    else:
        hint = "Verify Omnigent login and the SESSION_ID=HOST_ID routing pair."
    return ActionError(
        f"{session_id}: {method} failed with HTTP {exc.code}: {detail or exc.reason}. {hint}"
    )


def _event_body(message: str) -> bytes:
    return json.dumps(
        {
            "type": "message",
            "data": {
                "role": "user",
                "content": [{"type": "input_text", "text": message}],
            },
        }
    ).encode()


def send_actions(
    server: str,
    targets: list[Target],
    message: str,
    header_factory: Callable[[str | None], dict[str, str]],
    *,
    opener=urllib.request.urlopen,
    timeout: float = 30.0,
) -> list[tuple[str, int]]:
    """POST one event per target, preserving each target's host routing key."""
    results: list[tuple[str, int]] = []
    base = server.rstrip("/")
    for target in targets:
        session = urllib.parse.quote(target.session_id, safe="")
        url = f"{base}/v1/sessions/{session}/events"
        request = urllib.request.Request(
            url,
            data=_event_body(message),
            headers=header_factory(target.host_id),
            method="POST",
        )
        try:
            with opener(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raise _http_error(target.session_id, "POST", exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ActionError(
                f"{target.session_id}: POST could not reach {server}: {exc}"
            ) from exc
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ActionError(
                f"{target.session_id}: HTTP {status} returned malformed JSON"
            ) from exc
        if status != 202 or payload.get("queued") is not True:
            raise ActionError(
                f"{target.session_id}: expected 202 queued=true, got HTTP {status} {payload!r}"
            )
        results.append((target.session_id, status))
    return results


def error_code(session: dict) -> str | None:
    """Read ``labels.omnigent.last_task_error_code`` through either observed shape.

    Servers have been seen flattening the label into one dotted key and nesting it
    under ``labels.omnigent``. Accept both; an absent label means "no task error",
    which is itself the answer (#1825).
    """
    labels = session.get("labels")
    if not isinstance(labels, dict):
        return None
    candidates = [labels.get(ERROR_CODE_LABEL)]
    nested = labels.get("omnigent")
    if isinstance(nested, dict):
        candidates.append(nested.get("last_task_error_code"))
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def recovery_verdict(session: dict) -> tuple[str, str]:
    """``(verdict, why)`` — *genuinely dead, relaunch* vs *routing-blocked, re-send*.

    The question the whole recovery cascade exists to answer, from one GET.
    """
    code = error_code(session)
    if code in RUNNER_GONE_CODES:
        return (
            "relaunch",
            f"last_task_error_code={code}: the runner process is gone, so no nudge "
            "can reach it. Relaunch in place — same brief, same worktree.",
        )
    if code:
        return (
            "inspect",
            f"last_task_error_code={code}: neither a clean finish nor a routing "
            "problem. Read the code before acting.",
        )
    return (
        "re-send",
        "no last_task_error_code: nothing killed the last task, so this is idle or "
        "routing-blocked. Nudge it before considering a relaunch.",
    )


def probe_sessions(
    server: str,
    targets: list[Target],
    header_factory: Callable[[str | None], dict[str, str]],
    *,
    opener=urllib.request.urlopen,
    timeout: float = 15.0,
) -> list[dict[str, object]]:
    """GET /v1/sessions/{id} per target. Reads only — nothing is mutated."""
    rows: list[dict[str, object]] = []
    base = server.rstrip("/")
    for target in targets:
        session = urllib.parse.quote(target.session_id, safe="")
        url = f"{base}/v1/sessions/{session}"
        request = urllib.request.Request(
            url, headers=header_factory(target.host_id), method="GET"
        )
        try:
            with opener(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise _http_error(target.session_id, "GET", exc) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ActionError(
                f"{target.session_id}: GET could not reach {server}: {exc}"
            ) from exc
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise ActionError(
                f"{target.session_id}: GET returned malformed JSON"
            ) from exc
        record = payload.get("session") if isinstance(payload.get("session"), dict) else payload
        if not isinstance(record, dict):
            raise ActionError(
                f"{target.session_id}: GET returned no session object "
                "(api_shape_drift — log it)"
            )
        verdict, why = recovery_verdict(record)
        rows.append(
            {
                "session_id": target.session_id,
                "status": record.get("status"),
                "runner_online": record.get("runner_online"),
                "last_task_error_code": error_code(record),
                "verdict": verdict,
                "why": why,
            }
        )
    return rows


def _print_probe(rows: list[dict[str, object]]) -> None:
    print("session_id\tstatus\trunner_online\tlast_task_error_code\tverdict")
    for row in rows:
        print(
            f"{row['session_id']}\t{row['status']}\t{row['runner_online']}\t"
            f"{row['last_task_error_code'] or '-'}\t{row['verdict']}"
        )
    for row in rows:
        print(f"    {row['session_id']}: {row['why']}")


def _print_plan(action: str, targets: list[Target]) -> None:
    print("session_id\thost_id\taction")
    for target in targets:
        print(f"{target.session_id}\t{target.host_id or '-'}\t{action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--server", required=True, help="Omnigent server base URL")
    parser.add_argument(
        "--profile",
        help="Databricks profile when host-keyed OAuth cannot resolve the saved workspace",
    )
    parser.add_argument("--message", help="override the action's standard message")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="confirm the displayed nudge targets and mutate them",
    )
    parser.add_argument(
        "action",
        choices=ACTIONS,
        help="probe reads labels.omnigent.last_task_error_code; the rest post an event",
    )
    parser.add_argument("targets", nargs="+", metavar="SESSION_ID[=HOST_ID]")
    args = parser.parse_args(argv)

    try:
        targets = parse_targets(args.targets, remote=is_remote(args.server))
        _print_plan(args.action, targets)
        if args.action == "probe":
            _print_probe(
                probe_sessions(
                    args.server, targets, make_header_factory(args.server, args.profile)
                )
            )
            return 0
        if requires_confirmation(args.action) and not args.confirm:
            print("No events sent. Confirm this exact list, then rerun with --confirm.")
            return 2
        headers = make_header_factory(args.server, args.profile)
        results = send_actions(
            args.server,
            targets,
            args.message or DEFAULT_MESSAGES[args.action],
            headers,
        )
    except ActionError as exc:
        print(f"fleet_action: {exc}", file=sys.stderr)
        return 1

    for session_id, status in results:
        print(f"{session_id}\t{status}\tqueued")
    return 0


if __name__ == "__main__":
    sys.exit(main())
