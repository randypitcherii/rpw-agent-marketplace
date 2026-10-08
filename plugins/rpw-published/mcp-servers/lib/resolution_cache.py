"""Short-TTL on-disk cache for resolved credential state.

Credential resolution can invoke the Databricks CLI and make network round trips on every short-lived MCP process. This module lets resolvers reuse a fresh result for minutes, not hours.

The cache uses a per-user mode-0600 state file instead of the OS keyring. This avoids extra keychain contention and headless keychain prompts while keeping the same user-level trust boundary as the Databricks CLI configuration and token cache.

Fail-safe contract (the load-bearing property):

- ``load()`` returns the cached payload ONLY for a fresh, well-formed,
  identity-matching, tightly-permissioned entry. Anything else — missing file,
  expired TTL, corrupt JSON, schema mismatch, loose permissions, future
  timestamp (clock skew), unreadable dir, unexpected exception — returns
  ``None`` so the caller falls through to the real resolution path.
- ``store()`` is best-effort and never raises: a read-only HOME or full disk
  degrades to "no caching" (every invocation resolves fresh), never to a
  startup failure. This preserves the #428 degraded-startup semantics: the
  cache can only ever *remove* work from the pre-flight, never add a new way
  for it to die.
- Staleness bound: the TTL is short (default 5 minutes). A credential revoked
  upstream inside that window surfaces as a runtime auth error, which the
  existing machinery already turns actionable (``uc_oauth_reauthentication_
  required`` envelopes, stale-auth guards); the next process start after expiry
  re-verifies for real.

Knobs (env vars):

- ``RPW_CRED_CACHE_DISABLE=1`` — turn the cache off entirely (load misses,
  store no-ops).
- ``RPW_CRED_CACHE_TTL_SECONDS`` — override the TTL; ``<= 0`` disables.
- ``RPW_CRED_CACHE_DIR`` — override the cache directory (used by tests; also
  an escape hatch for exotic HOME layouts).

Default location: ``$XDG_STATE_HOME/rpw-mcp-servers/credential-cache`` (or
``~/.local/state/rpw-mcp-servers/credential-cache``) — a standard per-user
local state dir, never inside the repo. Directory is created 0700; entries are
written 0600 via an atomic temp-file + ``os.replace`` so concurrent processes
(parallel MCP server startups) can only ever observe a complete entry.

Import mechanism note: like the rest of ``lib/``, this is *not* a distributed
package — servers put the sibling ``mcp-servers/`` dir on ``sys.path`` before
``from lib import resolution_cache``. The lib ships duplicated per-plugin
(byte-identical, guarded by a repo-validation test). See ADR-2026-06-22.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from pathlib import Path
from typing import Any, Optional

# Short TTL by design: minutes, not hours. Long enough to absorb the bursty
# multi-server / repeated-CLI-invocation pattern that motivated #420, short
# enough that a revoked credential or flipped connection flavor is picked up
# within one coffee-sip.
DEFAULT_TTL_SECONDS = 300

# Tolerated clock skew before a future-dated entry is treated as corrupt.
_FUTURE_SKEW_SECONDS = 60

# Permission bits that must NOT be set on a trusted cache entry.
_GROUP_OTHER_BITS = stat.S_IRWXG | stat.S_IRWXO

_DISABLE_ENV = "RPW_CRED_CACHE_DISABLE"
_TTL_ENV = "RPW_CRED_CACHE_TTL_SECONDS"
_DIR_ENV = "RPW_CRED_CACHE_DIR"

_SCHEMA_VERSION = 1


def ttl_seconds() -> float:
    """Effective TTL: env override when parseable, else the default."""
    raw = (os.environ.get(_TTL_ENV) or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return float(DEFAULT_TTL_SECONDS)


def enabled() -> bool:
    """False when the disable flag is set or the effective TTL is <= 0."""
    if (os.environ.get(_DISABLE_ENV) or "").strip().lower() in {"1", "true", "yes"}:
        return False
    return ttl_seconds() > 0


def cache_dir() -> Path:
    """Per-user cache directory (NOT created here; ``store`` creates on demand)."""
    override = (os.environ.get(_DIR_ENV) or "").strip()
    if override:
        return Path(override)
    xdg_state = (os.environ.get("XDG_STATE_HOME") or "").strip()
    state_root = Path(xdg_state) if xdg_state else Path.home() / ".local" / "state"
    return state_root / "rpw-mcp-servers" / "credential-cache"


def _entry_path(kind: str, identity: dict[str, Any]) -> Path:
    digest = hashlib.sha256(
        json.dumps({"kind": kind, "identity": identity}, sort_keys=True).encode()
    ).hexdigest()[:16]
    return cache_dir() / f"{kind}-{digest}.json"


def _permissions_are_tight(path: Path) -> bool:
    mode = path.stat().st_mode
    return not (mode & _GROUP_OTHER_BITS)


def load(kind: str, identity: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return the cached payload for (kind, identity), or None (= resolve fresh).

    Every failure mode is a miss, never an exception: this function must be
    safe to call unconditionally at the top of a resolver.
    """
    try:
        if not enabled():
            return None
        path = _entry_path(kind, identity)
        if not path.is_file():
            return None
        if not _permissions_are_tight(path):
            # Someone loosened the entry (or it was created by older/foreign
            # tooling). Don't trust it — and don't leave it lying around.
            path.unlink(missing_ok=True)
            return None
        entry = json.loads(path.read_text())
        if not isinstance(entry, dict) or entry.get("schema") != _SCHEMA_VERSION:
            return None
        if entry.get("kind") != kind or entry.get("identity") != identity:
            return None
        created_at = entry.get("created_at")
        if not isinstance(created_at, (int, float)):
            return None
        now = time.time()
        if created_at > now + _FUTURE_SKEW_SECONDS:
            return None
        if now - created_at > ttl_seconds():
            return None
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return None
        return payload
    except Exception:
        # Fail safe: any surprise (unreadable dir, encoding, races) is a miss.
        return None


def store(kind: str, identity: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Best-effort write of a cache entry. Returns True on success, never raises.

    Atomic (temp file + ``os.replace``) so a concurrent reader can only see a
    complete entry; the temp file is opened 0600 from birth so the credential
    bytes are never world-readable, even transiently.
    """
    try:
        if not enabled():
            return False
        directory = cache_dir()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = _entry_path(kind, identity)
        entry = {
            "schema": _SCHEMA_VERSION,
            "kind": kind,
            "identity": identity,
            "created_at": time.time(),
            "payload": payload,
        }
        tmp = directory / f".{path.name}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(entry, handle)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        os.replace(tmp, path)
        os.chmod(path, 0o600)
        return True
    except Exception:
        return False


def invalidate(kind: str, identity: dict[str, Any]) -> None:
    """Best-effort removal of a cache entry (e.g. when its shape is unusable)."""
    try:
        _entry_path(kind, identity).unlink(missing_ok=True)
    except Exception:
        pass
