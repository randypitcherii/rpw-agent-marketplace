"""Zerobus sink: ship rpw log events to one Unity Catalog table, never at the app's expense.

Every rpw application already logs locally (``SQLiteLogStore``, stderr, files). This module
adds a second, *additive* destination: one append-only Unity Catalog Delta table (defined by
the ``projects/custom-logging`` bundle), written over the Zerobus Ingest REST API. The local
log stays the source of truth for the app; the table is the one place to ask "what happened
across all my stuff in the last hour" with SQL (#891).

Contract
--------

- **Never takes the app down.** ``submit`` is a non-blocking put on a bounded queue. A
  background daemon thread batches, authenticates and POSTs. Every failure — no credentials,
  no network, IP access list, schema rejection — is counted, warned about ONCE per cause on
  the ``rpw_logging.zerobus`` logger (Python's last-resort handler prints it to stderr when the
  app configured nothing), and the batch is dropped. The local log still has the event.
- **Redacted before it leaves the process.** The table is readable by every principal in the
  workspace, so ``message`` goes through ``redact_text`` and the payload through
  ``redact_value`` here, whatever the caller already did (both are idempotent).
- **Stdlib only.** ``urllib`` + ``threading``; no SDK, no protobuf. The file is also vendored
  into the MCP server lib (``scripts/sync_mcp_lib.py``), so it imports only ``.redaction``.
- **No secrets on disk.** Credentials come from the environment, or are read at runtime from
  a workspace secret scope with the user's own ``databricks auth token``. The
  Zerobus access token is cached in memory only.

Configuration (process env wins, then ``~/.rpw/logging.env``, then built-in defaults)
-------------------------------------------------------------------------------------

``RPW_LOGGING_ZEROBUS``                 ``auto`` (default) | ``on`` | ``off``. ``auto`` is on
                                        unless running under pytest or unittest.
``RPW_LOGGING_ZEROBUS_WORKSPACE_URL``   Workspace that owns the table and mints tokens.
``RPW_LOGGING_ZEROBUS_WORKSPACE_ID``    Numeric workspace id (the Zerobus host and token
                                        resource are keyed by it).
``RPW_LOGGING_ZEROBUS_REGION``          Cloud region of the workspace, e.g. ``us-east-1``.
``RPW_LOGGING_ZEROBUS_ENDPOINT``        Override the derived ``https://<id>.zerobus.<region>…``.
``RPW_LOGGING_ZEROBUS_TABLE``           ``catalog.schema.table`` to append to.
``RPW_LOGGING_ZEROBUS_CLIENT_ID``       Writer service principal (skips the secret scope).
``RPW_LOGGING_ZEROBUS_CLIENT_SECRET``   Its OAuth secret.
``RPW_LOGGING_ZEROBUS_SECRET_SCOPE``    Scope holding ``client_id`` / ``client_secret``.
``RPW_LOGGING_ZEROBUS_PROFILE``         ``~/.databrickscfg`` profile used to read the scope.
``RPW_LOGGING_ENVIRONMENT``             ``dev`` | ``test`` | ``prod``; falls back to ``APP_ENV``.
``RPW_LOGGING_APPLICATION_NAME``        Default ``application_name`` when a caller gives none.
``RPW_LOGGING_ENV_FILE``                Alternative path to the user-level ``logging.env``.

The built-in defaults (the maintainer's workspace) live in ``_defaults.py``, which is NOT vendored into
the public plugin: a published copy with no config is simply off.

Wire encoding (verified live, see projects/custom-logging/AGENTS.md): TIMESTAMP is an int of
epoch microseconds, VARIANT is a JSON *string*, BINARY is base64. Only the table's known
columns are sent — Zerobus rejects an unknown field (error 4044) for the whole request.
"""

from __future__ import annotations

import atexit
import base64
import configparser
import getpass
import json
import logging
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .redaction import redact_text, redact_value

try:  # private defaults; absent from the vendored public copy
    from ._defaults import DEFAULTS as _BUILTIN_DEFAULTS
except ImportError:  # pragma: no cover - exercised only in the vendored copy
    _BUILTIN_DEFAULTS: dict[str, str] = {}

log = logging.getLogger("rpw_logging.zerobus")

#: Wire-contract version, mirrored in ``projects/custom-logging/sql/log_events.sql``.
SCHEMA_VERSION = 1

#: The table's columns and their Delta types. ``projects/custom-logging/tests/
#: test_client_parity.py`` fails if this drifts from ``sql/log_events.sql``.
#: ``_rescued_data`` is service-owned and deliberately absent: the client never writes it.
WIRE_COLUMNS: dict[str, str] = {
    "event_id": "STRING",
    "event_timestamp": "TIMESTAMP",
    "ingested_at": "TIMESTAMP",
    "application_name": "STRING",
    "application_version": "STRING",
    "deployment_environment": "STRING",
    "severity": "STRING",
    "severity_number": "INT",
    "event_name": "STRING",
    "logger_name": "STRING",
    "message": "STRING",
    "host_name": "STRING",
    "user_name": "STRING",
    "session_id": "STRING",
    "trace_id": "STRING",
    "span_id": "STRING",
    "payload": "VARIANT",
    "payload_text": "STRING",
    "payload_binary": "BINARY",
    "schema_version": "INT",
}
REQUIRED_COLUMNS = (
    "event_id",
    "event_timestamp",
    "ingested_at",
    "application_name",
    "deployment_environment",
    "severity",
    "schema_version",
)

#: OpenTelemetry severity text -> number. Aliases normalize framework spellings.
SEVERITY_NUMBERS = {"TRACE": 1, "DEBUG": 5, "INFO": 9, "WARN": 13, "ERROR": 17, "FATAL": 21}
_SEVERITY_ALIASES = {
    "WARNING": "WARN",
    "CRITICAL": "FATAL",
    "EXCEPTION": "ERROR",
    "ERR": "ERROR",
    "NOTICE": "INFO",
    "SUCCESS": "INFO",
    "NOTSET": "TRACE",
}
_ENVIRONMENTS = ("dev", "test", "prod")

#: Keep one record well under Zerobus' 10 MB limit; a log row this big is a bug upstream.
MAX_PAYLOAD_BYTES = 1_000_000
MAX_MESSAGE_CHARS = 16_000
_MAX_BATCH_ROWS = 200
_MAX_BATCH_BYTES = 4_000_000
_QUEUE_SIZE = 10_000
_HTTP_TIMEOUT = 10.0
_RETRIES = 3
_CRED_RETRY_SECONDS = 600.0
_TOKEN_SLACK_SECONDS = 300.0


# ── configuration ────────────────────────────────────────────────────────────────


def _env_file_values(path: Path) -> dict[str, str]:
    """Parse a dotenv-style file (KEY=VALUE, # comments, optional quotes, ``export``)."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _under_unittest() -> bool:
    """``python -m unittest`` sets no env marker; its ``__main__`` module is the tell."""
    spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    return getattr(spec, "name", "") in ("unittest.__main__", "pytest.__main__")


def user_env_file() -> Path:
    override = os.environ.get("RPW_LOGGING_ENV_FILE")
    return Path(override).expanduser() if override else Path.home() / ".rpw" / "logging.env"


@dataclass(frozen=True)
class ZerobusConfig:
    enabled: bool
    reason: str
    workspace_url: str = ""
    workspace_id: str = ""
    region: str = ""
    endpoint: str = ""
    table: str = ""
    client_id: str = ""
    client_secret: str = field(default="", repr=False)
    secret_scope: str = ""
    profile: str = ""
    environment: str = "dev"
    application_name: str = ""
    exit_flush_seconds: float = 3.0

    def describe(self) -> dict[str, Any]:
        """Everything but the secret — safe to print."""
        return {
            "enabled": self.enabled,
            "reason": self.reason,
            "workspace_url": self.workspace_url,
            "workspace_id": self.workspace_id,
            "endpoint": self.endpoint,
            "table": self.table,
            "credentials": (
                "env" if self.client_id and self.client_secret
                else f"secret scope {self.secret_scope}" if self.secret_scope
                else "none"
            ),
            "profile": self.profile or "(auto)",
            "environment": self.environment,
        }


def resolve_config(env: Mapping[str, str] | None = None) -> ZerobusConfig:
    """Resolve the sink config: process env > user logging.env > built-in defaults."""
    process = dict(os.environ if env is None else env)
    merged: dict[str, str] = dict(_BUILTIN_DEFAULTS)
    if env is None:
        merged.update(_env_file_values(user_env_file()))
    merged.update({k: v for k, v in process.items() if v != ""})

    def get(key: str) -> str:
        return merged.get(key, "").strip()

    mode = (get("RPW_LOGGING_ZEROBUS") or "auto").lower()
    environment = (get("RPW_LOGGING_ENVIRONMENT") or get("APP_ENV") or "dev").lower()
    if environment not in _ENVIRONMENTS:
        environment = "dev"
    workspace_url = get("RPW_LOGGING_ZEROBUS_WORKSPACE_URL").rstrip("/")
    workspace_id = get("RPW_LOGGING_ZEROBUS_WORKSPACE_ID")
    region = get("RPW_LOGGING_ZEROBUS_REGION")
    endpoint = get("RPW_LOGGING_ZEROBUS_ENDPOINT").rstrip("/")
    if not endpoint and workspace_id and region:
        endpoint = f"https://{workspace_id}.zerobus.{region}.cloud.databricks.com"
    try:
        exit_flush = float(get("RPW_LOGGING_ZEROBUS_EXIT_FLUSH_SECONDS") or 3.0)
    except ValueError:
        exit_flush = 3.0

    base = ZerobusConfig(
        enabled=False,
        reason="",
        workspace_url=workspace_url,
        workspace_id=workspace_id,
        region=region,
        endpoint=endpoint,
        table=get("RPW_LOGGING_ZEROBUS_TABLE"),
        client_id=get("RPW_LOGGING_ZEROBUS_CLIENT_ID"),
        client_secret=get("RPW_LOGGING_ZEROBUS_CLIENT_SECRET"),
        secret_scope=get("RPW_LOGGING_ZEROBUS_SECRET_SCOPE"),
        profile=get("RPW_LOGGING_ZEROBUS_PROFILE"),
        environment=environment,
        application_name=get("RPW_LOGGING_APPLICATION_NAME"),
        exit_flush_seconds=max(0.0, exit_flush),
    )
    if mode in ("off", "0", "false", "no", "disabled"):
        return replace(base, reason="disabled by RPW_LOGGING_ZEROBUS")
    if mode == "auto" and ("PYTEST_VERSION" in process or (env is None and _under_unittest())):
        return replace(base, reason="auto-off under a test runner (set RPW_LOGGING_ZEROBUS=on)")
    missing = [
        name
        for name, value in (
            ("RPW_LOGGING_ZEROBUS_WORKSPACE_URL", workspace_url),
            ("RPW_LOGGING_ZEROBUS_WORKSPACE_ID", workspace_id),
            ("RPW_LOGGING_ZEROBUS_ENDPOINT", endpoint),
            ("RPW_LOGGING_ZEROBUS_TABLE", base.table),
        )
        if not value
    ]
    if base.table and base.table.count(".") != 2:
        missing.append("RPW_LOGGING_ZEROBUS_TABLE (catalog.schema.table)")
    if not (base.client_id and base.client_secret) and not base.secret_scope:
        missing.append("RPW_LOGGING_ZEROBUS_CLIENT_ID/_CLIENT_SECRET or _SECRET_SCOPE")
    if missing:
        return replace(base, reason="not configured: " + ", ".join(missing))
    return replace(base, enabled=True, reason="configured")


# ── row building ─────────────────────────────────────────────────────────────────


def normalize_severity(level: Any) -> tuple[str, int | None]:
    """Map a framework level (``"warning"``, ``logging.ERROR``, ``"err"``) to OTel text+number."""
    if isinstance(level, int) and not isinstance(level, bool):
        for threshold, text in ((50, "FATAL"), (40, "ERROR"), (30, "WARN"), (20, "INFO"), (10, "DEBUG")):
            if level >= threshold:
                return text, SEVERITY_NUMBERS[text]
        return "TRACE", SEVERITY_NUMBERS["TRACE"]
    text = str(level or "INFO").strip().upper() or "INFO"
    text = _SEVERITY_ALIASES.get(text, text)
    return text, SEVERITY_NUMBERS.get(text)


def to_epoch_micros(value: Any = None) -> int:
    """Encode a timestamp for the wire: epoch microseconds, UTC. ``None`` means now."""
    if value is None:
        return time.time_ns() // 1_000
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1_000_000)
    if isinstance(value, int | float) and not isinstance(value, bool):
        # seconds (1.7e9), millis (1.7e12) or micros (1.7e15) — pick by magnitude
        if value > 1e14:
            return int(value)
        if value > 1e11:
            return int(value * 1_000)
        return int(value * 1_000_000)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        return to_epoch_micros(datetime.fromisoformat(text))
    raise TypeError(f"unsupported timestamp {type(value).__name__}")


_HOST = socket.gethostname()


def _user() -> str | None:
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - no passwd entry in some containers
        return None


_USER = _user()


def _encode_payload(payload: Any) -> dict[str, Any]:
    if payload is None:
        return {}
    if isinstance(payload, bytes | bytearray | memoryview):
        raw = bytes(payload)[:MAX_PAYLOAD_BYTES]
        return {"payload_binary": base64.b64encode(raw).decode("ascii")}
    if isinstance(payload, str):
        return {"payload_text": redact_text(payload)[:MAX_PAYLOAD_BYTES]}
    scrubbed = redact_value(payload)
    try:
        text = json.dumps(scrubbed, default=str, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return {"payload_text": redact_text(repr(scrubbed))[:MAX_PAYLOAD_BYTES]}
    if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        return {"payload_text": text[:MAX_PAYLOAD_BYTES] + "...(truncated)"}
    return {"payload": text}


def build_row(
    *,
    application_name: str,
    severity: Any = "INFO",
    message: str | None = None,
    event_name: str | None = None,
    logger_name: str | None = None,
    payload: Any = None,
    event_timestamp: Any = None,
    session_id: str | None = None,
    trace_id: str | None = None,
    span_id: str | None = None,
    application_version: str | None = None,
    deployment_environment: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Build one wire row. ``ingested_at`` is stamped later, at submission time."""
    text, number = normalize_severity(severity)
    env = (deployment_environment or "").lower()
    row: dict[str, Any] = {
        "event_id": event_id or str(uuid.uuid4()),
        "event_timestamp": to_epoch_micros(event_timestamp),
        "application_name": application_name or "unknown",
        "application_version": application_version,
        "deployment_environment": env if env in _ENVIRONMENTS else None,
        "severity": text,
        "severity_number": number,
        "event_name": event_name,
        "logger_name": logger_name,
        "message": redact_text(message)[:MAX_MESSAGE_CHARS] if message else message,
        "host_name": _HOST,
        "user_name": _USER,
        "session_id": session_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "schema_version": SCHEMA_VERSION,
    }
    row.update(_encode_payload(payload))
    return {k: v for k, v in row.items() if v is not None}


def event_record_row(event: Any, *, created_at: str | None, application_name: str) -> dict[str, Any]:
    """Map an ``rpw_logging.EventRecord`` onto the table's columns.

    ``source`` is the component (``logger_name``), ``event_type`` the stable event name; the
    Slack/agent-specific fields and ``metadata_json`` travel in the VARIANT payload.
    """
    extras = {
        name: getattr(event, name, None)
        for name in (
            "run_id",
            "thread_ts",
            "trigger_message_ts",
            "trigger_type",
            "slack_permalink",
            "response_text",
            "agent_name",
            "tool_name",
        )
    }
    payload: dict[str, Any] = {k: v for k, v in extras.items() if v is not None}
    metadata = getattr(event, "metadata_json", None)
    if metadata:
        try:
            payload["metadata"] = json.loads(metadata)
        except (TypeError, ValueError):
            payload["metadata_text"] = metadata
    return build_row(
        application_name=application_name,
        severity=event.level,
        message=event.message,
        event_name=event.event_type,
        logger_name=event.source,
        payload=payload or None,
        event_timestamp=created_at,
        session_id=event.session_id,
        trace_id=event.trace_id,
    )


# ── credentials + transport ─────────────────────────────────────────────────────


class _SinkError(Exception):
    def __init__(self, cause: str, detail: str = "", *, retryable: bool = False) -> None:
        super().__init__(f"{cause}: {detail}" if detail else cause)
        self.cause = cause
        self.retryable = retryable


def _http(req: urllib.request.Request) -> Any:
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310 - https only
            body = resp.read()
    except urllib.error.HTTPError as exc:
        detail = redact_text(exc.read()[:500].decode("utf-8", "replace"))
        retryable = exc.code == 429 or exc.code >= 500
        raise _SinkError(f"http_{exc.code}", detail, retryable=retryable) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise _SinkError("network", redact_text(str(exc)), retryable=True) from exc
    return json.loads(body) if body.strip() else {}


def _profiles_for_host(host: str) -> list[str]:
    path = Path(os.environ.get("DATABRICKS_CONFIG_FILE", "~/.databrickscfg")).expanduser()
    parser = configparser.ConfigParser()
    try:
        parser.read(path)
    except configparser.Error:
        return []
    names = [
        name
        for name in ["DEFAULT", *parser.sections()]
        if parser.get(name, "host", fallback="").rstrip("/") == host
    ]
    return list(dict.fromkeys(names))


def _databricks_cli() -> str:
    """The CLI path. LaunchAgents run with a bare PATH, so look in the usual installs too."""
    found = shutil.which("databricks")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/databricks", "/usr/local/bin/databricks"):
        if os.access(candidate, os.X_OK):
            return candidate
    return "databricks"


def _user_token(cfg: ZerobusConfig) -> str:
    """The logged-in user's workspace token, via the Databricks CLI (never stored)."""
    candidates = [cfg.profile] if cfg.profile else _profiles_for_host(cfg.workspace_url) or [""]
    last = ""
    for profile in candidates:
        cmd = [_databricks_cli(), "auth", "token", "-o", "json"]
        cmd += ["--profile", profile] if profile else ["--host", cfg.workspace_url]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            last = str(exc)
            continue
        if out.returncode == 0:
            try:
                return json.loads(out.stdout)["access_token"]
            except (ValueError, KeyError):
                last = "unparseable token output"
                continue
        last = (out.stderr or out.stdout).strip().splitlines()[0:1]
        last = last[0] if last else f"exit {out.returncode}"
    raise _SinkError("user_auth", redact_text(last))


def _scope_secret(cfg: ZerobusConfig, user_token: str, key: str) -> str:
    query = urllib.parse.urlencode({"scope": cfg.secret_scope, "key": key})
    req = urllib.request.Request(
        f"{cfg.workspace_url}/api/2.0/secrets/get?{query}",
        headers={"Authorization": f"Bearer {user_token}"},
    )
    value = _http(req).get("value", "")
    return base64.b64decode(value).decode("utf-8").strip()


def resolve_client_credentials(cfg: ZerobusConfig) -> tuple[str, str]:
    """(client_id, client_secret) from env, else the secret scope read as the current user."""
    if cfg.client_id and cfg.client_secret:
        return cfg.client_id, cfg.client_secret
    token = _user_token(cfg)
    return _scope_secret(cfg, token, "client_id"), _scope_secret(cfg, token, "client_secret")


def mint_token(cfg: ZerobusConfig, client_id: str, client_secret: str) -> tuple[str, float]:
    """A table-scoped Zerobus token for the writer SP. Returns (token, expires_at_epoch)."""
    catalog, schema, _ = cfg.table.split(".")
    authz = [
        {
            "type": "unity_catalog_privileges",
            "privileges": ["USE CATALOG"],
            "object_type": "CATALOG",
            "object_full_path": catalog,
        },
        {
            "type": "unity_catalog_privileges",
            "privileges": ["USE SCHEMA"],
            "object_type": "SCHEMA",
            "object_full_path": f"{catalog}.{schema}",
        },
        {
            "type": "unity_catalog_privileges",
            "privileges": ["SELECT", "MODIFY"],
            "object_type": "TABLE",
            "object_full_path": cfg.table,
        },
    ]
    data = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "scope": "all-apis",
            "resource": f"api://databricks/workspaces/{cfg.workspace_id}/zerobusDirectWriteApi",
            "authorization_details": json.dumps(authz),
        }
    ).encode()
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    req = urllib.request.Request(
        f"{cfg.workspace_url}/oidc/v1/token",
        data=data,
        headers={"Authorization": f"Basic {basic}"},
    )
    body = _http(req)
    return body["access_token"], time.time() + float(body.get("expires_in", 3600))


# ── the sink ─────────────────────────────────────────────────────────────────────


@dataclass
class SinkStats:
    submitted: int = 0
    sent: int = 0
    dropped: int = 0
    batches: int = 0
    last_error: str = ""


class ZerobusSink:
    """Batched, background, fail-safe Zerobus writer. One per process is plenty."""

    def __init__(self, config: ZerobusConfig | None = None) -> None:
        self.config = config or resolve_config()
        self.stats = SinkStats()
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=_QUEUE_SIZE)
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._pending = 0
        self._thread: threading.Thread | None = None
        self._pid = 0
        self._token = ""
        self._token_expires = 0.0
        self._creds: tuple[str, str] | None = None
        self._paused_until = 0.0
        self._warned: set[str] = set()
        self._atexit = False

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def submit(self, row: Mapping[str, Any]) -> bool:
        """Queue one row built by :func:`build_row`. Never blocks, never raises."""
        if not self.config.enabled:
            return False
        try:
            record = {k: v for k, v in row.items() if k in WIRE_COLUMNS and v is not None}
            record.setdefault("deployment_environment", self.config.environment)
            self._ensure_worker()
            with self._lock:
                self._pending += 1
                self.stats.submitted += 1
            try:
                self._queue.put_nowait(record)
            except queue.Full:
                self._done(1, dropped=True)
                self._warn_once("queue_full", "Zerobus queue full; dropping log events")
                return False
            return True
        except Exception as exc:  # noqa: BLE001 - logging must never raise into the app
            self._warn_once("submit", f"Zerobus submit failed: {exc!r}")
            return False

    def emit(self, **fields: Any) -> bool:
        """``build_row`` + ``submit``; ``application_name`` defaults from config."""
        fields.setdefault("application_name", self.config.application_name or _argv0())
        fields.setdefault("deployment_environment", self.config.environment)
        try:
            row = build_row(**fields)
        except Exception as exc:  # noqa: BLE001
            self._warn_once("build", f"Zerobus row build failed: {exc!r}")
            return False
        return self.submit(row)

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until every queued row was sent or dropped. True if drained in time."""
        deadline = time.monotonic() + timeout
        with self._idle:
            while self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._idle.wait(remaining)
        return True

    def status(self) -> dict[str, Any]:
        return {**self.config.describe(), **self.stats.__dict__, "pending": self._pending}

    # ── internals ──

    def _ensure_worker(self) -> None:
        if self._thread is not None and self._thread.is_alive() and self._pid == os.getpid():
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive() and self._pid == os.getpid():
                return
            if self._pid and self._pid != os.getpid():  # forked: the parent's queue is not ours
                self._queue = queue.Queue(maxsize=_QUEUE_SIZE)
                self._pending = 0
            self._pid = os.getpid()
            self._thread = threading.Thread(target=self._run, name="rpw-zerobus-sink", daemon=True)
            self._thread.start()
            if not self._atexit:
                atexit.register(self._exit_flush)
                self._atexit = True

    def _exit_flush(self) -> None:
        if self._pending and self.config.exit_flush_seconds > 0:
            self.flush(self.config.exit_flush_seconds)

    def _done(self, n: int, *, dropped: bool = False) -> None:
        with self._idle:
            self._pending = max(0, self._pending - n)
            if dropped:
                self.stats.dropped += n
            else:
                self.stats.sent += n
            self._idle.notify_all()

    def _warn_once(self, cause: str, message: str) -> None:
        self.stats.last_error = message
        if cause in self._warned:
            return
        self._warned.add(cause)
        try:
            log.warning("%s (local logging unaffected; further %s warnings suppressed)", message, cause)
        except Exception:  # noqa: BLE001
            pass

    def _run(self) -> None:
        while True:
            try:
                first = self._queue.get()
            except Exception:  # noqa: BLE001 - interpreter teardown
                return
            batch = [first]
            size = len(json.dumps(first, default=str))
            while len(batch) < _MAX_BATCH_ROWS and size < _MAX_BATCH_BYTES:
                try:
                    nxt = self._queue.get(timeout=0.05)
                except queue.Empty:
                    break
                batch.append(nxt)
                size += len(json.dumps(nxt, default=str))
            try:
                self._send(batch)
                self._done(len(batch))
            except _SinkError as exc:
                self._done(len(batch), dropped=True)
                self._warn_once(exc.cause, f"Zerobus dropped {len(batch)} log event(s): {exc}")
            except Exception as exc:  # noqa: BLE001
                self._done(len(batch), dropped=True)
                self._warn_once("unexpected", f"Zerobus dropped {len(batch)} log event(s): {exc!r}")

    def _access_token(self, *, force: bool = False) -> str:
        now = time.time()
        if not force and self._token and now < self._token_expires - _TOKEN_SLACK_SECONDS:
            return self._token
        if now < self._paused_until:
            raise _SinkError("credentials_paused", "retrying credential resolution later")
        try:
            if self._creds is None:
                self._creds = resolve_client_credentials(self.config)
            self._token, self._token_expires = mint_token(self.config, *self._creds)
        except _SinkError as exc:
            if not exc.retryable:  # bad/missing credentials: stop hammering for a while
                self._paused_until = now + _CRED_RETRY_SECONDS
                self._creds = None
            raise
        return self._token

    def _send(self, batch: list[dict[str, Any]]) -> None:
        self.stats.batches += 1
        url = f"{self.config.endpoint}/zerobus/v1/tables/{self.config.table}/insert"
        delay = 0.5
        refreshed = False
        for attempt in range(1, _RETRIES + 1):
            ingested = to_epoch_micros()
            for row in batch:
                row["ingested_at"] = ingested
            body = json.dumps(batch, default=str, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._access_token()}",
                },
            )
            try:
                _http(req)
                return
            except _SinkError as exc:
                if exc.cause in ("http_401", "http_403") and not refreshed:
                    refreshed = True
                    self._token = ""
                    continue
                if not exc.retryable or attempt == _RETRIES:
                    raise
            time.sleep(delay)
            delay *= 2


def _argv0() -> str:
    name = Path(sys.argv[0]).stem if sys.argv and sys.argv[0] else ""
    return name or "python"


# ── process-global convenience ──────────────────────────────────────────────────

_default_sink: ZerobusSink | None = None
_default_lock = threading.Lock()


def get_sink() -> ZerobusSink:
    """The process-wide sink, created on first use from :func:`resolve_config`."""
    global _default_sink
    if _default_sink is None:
        with _default_lock:
            if _default_sink is None:
                _default_sink = ZerobusSink()
    return _default_sink


def set_sink(sink: ZerobusSink | None) -> None:
    """Replace the process-wide sink (tests, or an app that builds its own config)."""
    global _default_sink
    with _default_lock:
        _default_sink = sink


def log_event(**fields: Any) -> bool:
    """Fire-and-forget one event on the process sink. See :func:`build_row` for fields."""
    try:
        return get_sink().emit(**fields)
    except Exception:  # noqa: BLE001
        return False


class ZerobusHandler(logging.Handler):
    """A stdlib ``logging`` handler that mirrors records to the Zerobus table.

    Attach it next to the app's existing handlers; it does not replace them. Records from
    this module's own logger are ignored so a sink warning can never recurse into the sink.
    """

    def __init__(
        self,
        application_name: str,
        *,
        level: int = logging.INFO,
        sink: ZerobusSink | None = None,
        application_version: str | None = None,
        session_id: str | None = None,
    ) -> None:
        super().__init__(level)
        self.application_name = application_name
        self.application_version = application_version
        self.session_id = session_id
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("rpw_logging.zerobus"):
            return
        try:
            sink = self._sink or get_sink()
            if not sink.enabled:
                return
            payload: dict[str, Any] = {
                "module": record.module,
                "func": record.funcName,
                "line": record.lineno,
                "process": record.process,
                "thread": record.threadName,
            }
            if record.exc_info:
                payload["exception"] = logging.Formatter().formatException(record.exc_info)
            sink.emit(
                application_name=self.application_name,
                application_version=self.application_version,
                severity=record.levelno,
                message=record.getMessage(),
                event_name=getattr(record, "event_name", None) or "log",
                logger_name=record.name,
                payload=payload,
                event_timestamp=record.created,
                session_id=getattr(record, "session_id", None) or self.session_id,
            )
        except Exception:  # noqa: BLE001 - a log handler must never raise
            pass


# ── short-lived processes: hand off, never wait ─────────────────────────────────
#
# A CLI or hook that used the in-process sink would pay the first token mint (the user's
# CLI token, a secret read, an OIDC exchange: seconds) at exit, on every invocation. So
# short-lived callers buffer rows in memory and, at exit, pipe them to a detached child
# running ``main(["emit"])``. The caller returns immediately; the child ships and exits.

_DETACHED_MAX_ROWS = 500
#: A positional that looks like a subcommand. Anything else (a prompt, a path, a token)
#: is never recorded, so argv content cannot leak into the table.
_COMMAND_SHAPE = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-_")


def _import_root() -> tuple[str, str]:
    """(sys.path entry, package) that re-imports this module in a child process.

    Canonical: ``.../src`` + ``rpw_logging``. Vendored into the MCP lib:
    ``.../mcp-servers`` + ``lib._rpw_logging``.
    """
    package = __package__ or "rpw_logging"
    root = Path(__file__).resolve().parents[len(package.split("."))]
    return str(root), package


def emit_detached(rows: list[Mapping[str, Any]], *, config: ZerobusConfig | None = None) -> bool:
    """Pipe ``build_row`` field dicts to a detached ``emit`` child. Never blocks or raises."""
    cfg = config or get_sink().config
    if not cfg.enabled or not rows:
        return False
    try:
        root, package = _import_root()
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); "
            "import importlib; "
            "sys.exit(importlib.import_module(sys.argv[2] + '.zerobus').main(['emit']))"
        )
        lines = "".join(
            json.dumps({k: v for k, v in r.items() if k in _BUILD_ROW_FIELDS}, default=str) + "\n"
            for r in rows[:_DETACHED_MAX_ROWS]
        )
        proc = subprocess.Popen(  # noqa: S603 - fixed argv, our own interpreter
            [sys.executable, "-c", code, root, package],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        assert proc.stdin is not None
        proc.stdin.write(lines.encode("utf-8"))
        proc.stdin.close()
        return True
    except Exception:  # noqa: BLE001 - telemetry must never break the caller
        return False


class DetachedSink:
    """``ZerobusSink``-shaped buffer for short-lived processes; ``flush`` hands off.

    ``event_id`` and ``event_timestamp`` are fixed at emit time, so the child's rows carry
    when things happened, not when the child got to them.
    """

    def __init__(self, config: ZerobusConfig | None = None) -> None:
        self.config = config or get_sink().config
        self.rows: list[dict[str, Any]] = []

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def emit(self, **fields: Any) -> bool:
        if not self.enabled or len(self.rows) >= _DETACHED_MAX_ROWS:
            return False
        fields.setdefault("event_id", str(uuid.uuid4()))
        fields["event_timestamp"] = to_epoch_micros(fields.get("event_timestamp"))
        self.rows.append(fields)
        return True

    def flush(self, timeout: float = 0.0) -> bool:  # noqa: ARG002 - sink-compatible signature
        rows, self.rows = self.rows, []
        return emit_detached(rows, config=self.config) if rows else True


def cli_command(argv: list[str] | None) -> str | None:
    """The subcommand from ``argv`` (first positional), only when it looks like one."""
    for arg in argv or []:
        if arg.startswith("-"):
            continue
        name = arg.lower()
        if 0 < len(name) <= 40 and set(name) <= _COMMAND_SHAPE:
            return name
        return None
    return None


def instrument_cli(
    application_name: str,
    *,
    application_version: str | None = None,
    level: int = logging.WARNING,
):
    """Decorate a CLI ``main(argv=None)``: one ``cli.invocation`` row per run, plus WARNING+.

    The row records the subcommand (never the rest of argv), exit code, duration and the
    exception type on a crash. Root-logger records at ``level``+ ride along. Everything is
    handed to a detached child at exit, so the CLI never waits on the network. A disabled
    sink (unconfigured, ``RPW_LOGGING_ZEROBUS=off``, under a test runner) is a passthrough.
    """

    def decorate(fn):
        import functools

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                sink = DetachedSink()
            except Exception:  # noqa: BLE001
                return fn(*args, **kwargs)
            if not sink.enabled:
                return fn(*args, **kwargs)
            argv = kwargs.get("argv", args[0] if args else None)
            argv = list(argv) if isinstance(argv, (list, tuple)) else sys.argv[1:]
            handler = ZerobusHandler(
                application_name, level=level, sink=sink, application_version=application_version
            )
            root = logging.getLogger()
            root.addHandler(handler)
            started = time.monotonic()
            exit_code: Any = 0
            error: str | None = None
            try:
                result = fn(*args, **kwargs)
                exit_code = result if isinstance(result, int) and not isinstance(result, bool) else 0
                return result
            except SystemExit as exc:
                code = exc.code
                exit_code = code if isinstance(code, int) else (0 if code is None else 1)
                raise
            except KeyboardInterrupt:
                exit_code, error = 130, "KeyboardInterrupt"
                raise
            except BaseException as exc:
                exit_code, error = 1, type(exc).__name__
                raise
            finally:
                root.removeHandler(handler)
                command = cli_command(argv)
                sink.emit(
                    application_name=application_name,
                    application_version=application_version,
                    event_name="cli.invocation",
                    severity="INFO" if exit_code == 0 else "ERROR",
                    message=f"{application_name} {command or ''} exited {exit_code}".replace("  ", " "),
                    logger_name="rpw_logging.cli",
                    payload={
                        "command": command,
                        "exit_code": exit_code,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "error": error,
                        "python": sys.version.split()[0],
                    },
                )
                sink.flush()

        return wrapper

    return decorate


# ── CLI ──────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    """``python -m rpw_logging status|test|emit`` — probe, smoke-test, or pipe events.

    ``emit`` reads one JSON object per stdin line (``build_row`` fields) and blocks until they
    are flushed — hooks call it detached so the hook itself returns immediately.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="python -m rpw_logging", description=main.__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="print the resolved config (no secrets)")
    t = sub.add_parser("test", help="send one test event and wait for the result")
    t.add_argument("--application-name", default="rpw_logging.zerobus")
    e = sub.add_parser("emit", help="send JSON-lines events from stdin")
    e.add_argument("--application-name", default=None)
    e.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    sink = get_sink()
    if args.cmd == "status":
        print(json.dumps(sink.config.describe(), indent=2))
        return 0
    if not sink.enabled:
        print(f"zerobus sink disabled: {sink.config.reason}", file=sys.stderr)
        return 0 if args.cmd == "emit" else 1
    if args.cmd == "test":
        event_id = str(uuid.uuid4())
        sink.emit(
            application_name=args.application_name,
            event_name="zerobus.test",
            message="rpw_logging zerobus smoke test",
            event_id=event_id,
        )
        ok = sink.flush(30.0) and sink.stats.sent == 1
        print(json.dumps({"ok": ok, "event_id": event_id, **sink.status()}, indent=2))
        return 0 if ok else 1
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            fields = json.loads(line)
        except ValueError:
            fields = {"message": line}
        if args.application_name:
            fields.setdefault("application_name", args.application_name)
        sink.emit(**{k: v for k, v in fields.items() if k in _BUILD_ROW_FIELDS})
    sink.flush(args.timeout)
    return 0


_BUILD_ROW_FIELDS = frozenset(
    (
        "application_name",
        "severity",
        "message",
        "event_name",
        "logger_name",
        "payload",
        "event_timestamp",
        "session_id",
        "trace_id",
        "span_id",
        "application_version",
        "deployment_environment",
        "event_id",
    )
)

