"""Secret redaction for structured log payloads — extracted from high-voltage's
``observability.py`` (#431 Phase 3), and the suite's ONE answer to "what does a secret
look like".

Two independent passes, because a secret can arrive either way:

- **by key** — ``{"api_key": "…"}``: the payload names the credential, so the whole value goes.
- **by shape** — ``{"error": "401 from https://…?token=dapi…"}``: nothing in the key says
  "secret", but the *value* carries a token-shaped substring. Key matching cannot see this,
  and truncation bounds how MUCH of it lands, never WHAT (#603/#628 — both issues are the
  same "bounded by length, never by content" blind spot, found in two different libs).

:func:`redact_text` is the shape pass on its own, exported so non-logging consumers with
free-text fields to scrub — the build ledger's ``worker_events.action`` / ``.detail``
(``rpw_runtime.telemetry``) — share this pattern list instead of growing a second one that
silently drifts from it.

Redaction errs toward over-scrubbing: a false positive costs one unreadable log line, a
false negative writes a live credential to disk.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_SECRET_KEYS = ("authorization", "token", "secret", "password", "api_key")

#: What every pass substitutes for the secret it found.
REDACTED = "***REDACTED***"

#: Strings longer than this are truncated (AFTER scrubbing — see :func:`redact_value`).
_MAX_STRING = 4000

#: The key half of the named-credential rule.
#:
#: ``GEMINI_API_KEY=…`` / ``AWS_SECRET_ACCESS_KEY=…`` / ``HF_TOKEN=…`` used to pass verbatim
#: because the rule opened with ``\b``: ``_`` is a word character, so the boundary NEVER fires
#: after it and every underscore-prefixed env var read as prose. Dropping the leading ``\b``
#: is the whole fix for the UNQUOTED form — the match simply starts at ``API_KEY`` and the
#: ``GEMINI_`` in front of it lies outside the match, surviving verbatim.
#:
#: The QUOTED form needs more: in ``{"db_password": "…"}`` the closing quote sits between the
#: key and the ``:``, so the match must begin at the opening quote and therefore has to walk
#: the ``db_`` prefix itself. That prefix walk is spelled out only inside the quoted
#: alternative (which cannot start anywhere but a quote character), so it costs nothing on
#: ordinary prose; spelling it in front of the bare form instead makes every offset in a long
#: word-run retry the prefix and slows the scan ~65×.
#:
#: The TRAILING ``\b`` is load-bearing in the other direction: it keeps the plural out, so
#: ``tokens=3`` (a count) still reads.
#:
#: That trailing ``\b`` is also why every ``<qualifier>_key`` credential has to be spelled
#: out as a NAME rather than left to the prefix walk: ``secret`` alone could never match
#: ``SECRET_KEY=…`` (``_`` is a word character, so the boundary never fires after ``secret``),
#: and the BARE alternative deliberately has no ``_KEY_PREFIX`` in front of it, so there was
#: nothing to walk the ``…_`` from the other side either. ``SECRET_KEY=``, ``PRIVATE_KEY=``
#: and friends passed through verbatim. ``key`` cannot be a name on its own — it is far too
#: common in ordinary log prose — so the qualifier list is enumerated instead.
#:
#: ``<qualifier>_token`` / ``<qualifier>_secret`` (``AUTH_TOKEN=``, ``CLIENT_SECRET=``) need
#: no such entry: the bare ``token`` / ``secret`` name matches with the qualifier falling
#: outside the match, exactly like ``GEMINI_API_KEY``.
_KEY_PREFIX = r"[A-Za-z0-9_-]{0,64}"
_KEY_NAMES = (
    r"(?:authorization"
    r"|(?:api|access|secret|private|session|signing|encryption|master|ssh)[_-]?key"
    r"|password|passwd|passphrase|secret|token)"
)

#: A quote character. The quoted alternative below closes on ANY quote rather than a
#: backreference to the one it opened with: a malformed or mixed repr (``"password': "…"``,
#: which is what a half-escaped dict stringification looks like in a log line) matched
#: NEITHER branch — the backreference failed, and the stray quote sat between the key and the
#: ``:`` so the bare branch never reached the separator. The bare branch likewise tolerates a
#: trailing quote it never saw opened. Mild over-redaction is the direction this module errs.
#:
#: Group numbering is load-bearing: ``_SECRET_PATTERNS``' named-credential replacement is
#: ``\g<1>\g<3>``, so group 1 must stay the key token and group 3 the separator. Group 2 (the
#: opening quote) is now unreferenced but stays CAPTURING to hold that numbering; everything
#: added here is non-capturing.
_QUOTE = r"[\"']"
_KEY_TOKEN = (
    # quoted: "db_password"  |  bare: token / GEMINI_API_KEY / SECRET_KEY / password'
    r"((" + _QUOTE + r")" + _KEY_PREFIX + _KEY_NAMES + r"\b" + _QUOTE
    + r"|" + _KEY_NAMES + r"\b" + _QUOTE + r"?)"
)

#: The value half. Terminated quoted forms come FIRST so the closing quote is consumed as
#: part of the secret; the unterminated forms are last, for the upstream-truncated string
#: (``token="abc123secretvalue`` with no closing quote) that would otherwise match nothing at
#: all and pass through verbatim.
_SECRET_VALUE = r"(\"[^\"]*\"|'[^']*'|[^\s,;&)}\]\"']+|\"[^\"]*|'[^']*)"

#: Value-shaped secret patterns, applied in order to every string that passes through.
#:
#: ``(pattern, replacement)``; a replacement may keep back-referenced context (the key name,
#: the ``Bearer`` scheme) so the scrubbed line still says WHAT was removed. Length floors
#: (``{16,}``) and "not preceded by a word character" lookbehinds keep ordinary prose out:
#: without them ``risk-assessment-summary`` reads as an ``sk-`` key.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # HTTP `Authorization: Bearer <token>` — the scheme stays, the credential goes. FIRST,
    # so the rule below sees `Authorization: Bearer ***REDACTED***` and has nothing left.
    (re.compile(r"(?i)\b(bearer)(\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\g<1>\g<2>" + REDACTED),
    # The other two HTTP auth schemes. `Basic <base64-of-user:pass>` is a full credential in
    # one token, so it cannot be left to the named rule (which only sees `Authorization:` and
    # stops at the scheme word). The scheme match is case-insensitive but the VALUE class is
    # NOT, because `(?i)` plus a naive value class redacts the middle of "basic auth
    # configuration reloaded". The lookahead demands the credential look like a credential:
    # a digit / `+` / `/` / `=` anywhere, or an uppercase letter that is not the first
    # character. Ordinary prose after the word (`basic understanding`, `digest
    # authentication`) has none of those and survives; a capitalized-word-with-inner-capitals
    # (`basic PostgreSQL setup`) is over-redacted, which is the direction this module errs.
    (
        re.compile(
            r"\b((?i:basic|digest))(\s+)"
            r"(?=[0-9+/=]|[A-Za-z0-9._~+/=-][A-Za-z0-9._~+/=-]*[0-9+/=A-Z])"
            r"[A-Za-z0-9._~+/=-]{8,}"
        ),
        r"\g<1>\g<2>" + REDACTED,
    ),
    # URL userinfo — `https://user:SuperSecret99@host/path`. The credential is positional:
    # no key names it and no shape rule recognizes it, so only the `scheme://user:` … `@`
    # frame gives it away. The user half is kept (it is identity, not a secret) so the
    # scrubbed URL still says which principal the call was made as.
    (re.compile(r"(://[^/\s@:]+:)[^@/\s]{3,}@"), r"\g<1>" + REDACTED + "@"),
    # A credential that names itself: `token=…`, `password: …`, `api_key="…"`, `SECRET_KEY=…`,
    # and — via the optional quotes in `_KEY_TOKEN` — the dict-repr form `{"password": "…"}`
    # that `worker_telemetry._compact` stringifies (the closing quote sits between the key and
    # the separator, so an unquoted rule never reaches the `:`). Quoted values are consumed whole
    # so the closing quote does not survive as noise; an auth SCHEME is not a value
    # (`Authorization: Bearer …` is the rules above's business).
    (
        re.compile(
            r"(?i)" + _KEY_TOKEN + r"(\s*[=:]\s*)"
            r"(?!(?:bearer|basic|digest)\b)" + _SECRET_VALUE
        ),
        r"\g<1>\g<3>" + REDACTED,
    ),
    # JWT / OAuth id tokens: base64url `{"alg"…` header, so always `eyJ`-prefixed.
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?"), REDACTED),
    # Slack: xoxb- / xoxp- / xoxa- / xoxs- / xoxe- …
    (re.compile(r"\bxox[a-z]-[A-Za-z0-9-]{10,}"), REDACTED),
    # Databricks PAT: `dapi` + 32 hex, optionally `-<n>` suffixed.
    (re.compile(r"(?<![A-Za-z0-9])dapi[0-9a-fA-F]{16,}(?:-\d+)?"), REDACTED),
    # OpenAI / Anthropic style: `sk-…`, `sk-ant-api03-…`.
    (re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{16,}"), REDACTED),
    # GitHub: ghp_ (PAT), gho_/ghu_/ghs_/ghr_ (OAuth, user, server, refresh).
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), REDACTED),
    # AWS access key id (and its STS/temporary sibling ASIA).
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{12,}"), REDACTED),
    # Google API key (Gemini, Maps, …): `AIza` + 35 more characters.
    (re.compile(r"(?<![A-Za-z0-9])AIza[0-9A-Za-z_-]{30,}"), REDACTED),
    # HuggingFace user access token: `hf_` + ~34 alphanumerics.
    (re.compile(r"(?<![A-Za-z0-9])hf_[A-Za-z0-9]{20,}"), REDACTED),
)

__all__ = ["REDACTED", "redact_text", "redact_value", "structured_log_payload"]


def redact_text(value: str) -> str:
    """Scrub secret-SHAPED substrings out of one free-text string.

    Content-based, so it catches the credential no key name announces: the token inside an
    exception message, a URL query parameter, a proxy's echoed response body. Idempotent —
    running it twice is the same as running it once, so callers may scrub defensively at
    more than one layer.
    """
    if not isinstance(value, str) or not value:
        return value
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def redact_value(value: Any) -> Any:
    """Recursively redact a log payload: by key, then by value shape, then by length.

    A value under a secret-shaped KEY is dropped whole (its shape is irrelevant — the key
    already told us). Everything else is walked, and every string is scrubbed for
    token-shaped content BEFORE the length cap, so a secret in the first 4000 characters is
    removed rather than merely accompanied by the truncation marker.
    """
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(secret_key in str(key).lower() for secret_key in _SECRET_KEYS):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        scrubbed = redact_text(value)
        if len(scrubbed) > _MAX_STRING:
            return scrubbed[:_MAX_STRING] + "...(truncated)"
        return scrubbed
    return value


def structured_log_payload(
    *,
    level: str,
    source: str,
    event_type: str,
    message: str,
    run_id: str | None = None,
    thread_ts: str | None = None,
    trigger_message_ts: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical structured log payload, with every free-text field scrubbed.

    ``message`` goes through :func:`redact_text` here rather than at each call site (#1406):
    it is a free-text field callers routinely f-string exception text, URLs and Slack content
    into, and "don't put a secret in the message string" is an unenforceable convention. Doing
    it in the shared lib means every consumer of this payload — and every sink fed from it —
    inherits the scrub instead of each having to remember.
    """
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "source": source,
        "event_type": event_type,
        "message": redact_text(message),
        "run_id": run_id,
        "thread_ts": thread_ts,
        "trigger_message_ts": trigger_message_ts,
    }
    if extra:
        payload.update(redact_value(extra))
    return payload
