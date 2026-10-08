"""
Auth and HTTP primitives for the Google Docs MCP server.

Uses gcloud ADC auth (same as vibe's google-tools): tokens come from
``gcloud auth application-default print-access-token`` and requests are issued
via ``curl`` (JSON API + authed binary fetch) and stdlib ``urllib`` (multipart
upload).

``api`` is the single shared JSON entry point; tests patch it (``auth.api``) to
run the whole server without live Google calls.
"""

import json
import os
import shutil
import subprocess
import time
from typing import Any, Dict, Optional

from config import QUOTA_PROJECT

# Timeouts (#423): a wedged curl/gcloud used to block the single-threaded stdio
# server indefinitely — the client's 300s timeout then killed the whole server.
# Every subprocess call gets a hard cap, and curl additionally gets its own
# --connect-timeout/--max-time so a stalled TCP connection fails fast.
GCLOUD_TIMEOUT_SECONDS = 30
CURL_CONNECT_TIMEOUT_SECONDS = 10
CURL_MAX_TIME_SECONDS = 120
# subprocess-level backstop: slightly above curl's own --max-time so curl gets
# the chance to fail cleanly first.
CURL_SUBPROCESS_TIMEOUT_SECONDS = CURL_MAX_TIME_SECONDS + 15

# 429 retry (#423 fix 4): now that error envelopes are visible, retry
# rate-limit rejections with simple exponential backoff before giving up.
API_MAX_ATTEMPTS = 3
API_BACKOFF_BASE_SECONDS = 1.0

# ADC token cache (#423): previously every api() call shelled out to gcloud,
# so a single large write_to_tab spawned one gcloud subprocess per batch.
# Tokens live ~1h; caching for a few minutes removes almost all of that churn
# while staying far inside the token lifetime. Failures are never cached.
TOKEN_CACHE_TTL_SECONDS = 300
_token_cache: Dict[str, Any] = {"token": None, "expires_at": 0.0}


class DocsApiError(RuntimeError):
    """A Google API call returned an error envelope ({"error": ...}).

    Carries the full envelope so callers can build structured failure results
    instead of losing the Google error detail in a string.
    """

    def __init__(self, envelope: Dict):
        self.envelope = envelope if isinstance(envelope, dict) else {"error": envelope}
        err = self.envelope.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or json.dumps(err)
        else:
            msg = str(err)
        super().__init__(msg)


def raise_for_error(resp: Any) -> Any:
    """Raise DocsApiError if resp is a Google error envelope; else pass it through."""
    if isinstance(resp, dict) and "error" in resp:
        raise DocsApiError(resp)
    return resp


def find_gcloud() -> str:
    gcloud = shutil.which("gcloud")
    if gcloud:
        return gcloud
    for p in [
        os.path.expanduser("~/google-cloud-sdk/bin/gcloud"),
        "/opt/homebrew/bin/gcloud",
        "/opt/homebrew/share/google-cloud-sdk/bin/gcloud",
        "/usr/local/bin/gcloud",
    ]:
        if os.path.exists(p):
            return p
    # Raise instead of sys.exit (#423): this runs inside the MCP server process,
    # so exiting here killed every gdocs_* tool for the rest of the session.
    raise RuntimeError("gcloud not found — install the Google Cloud SDK or add it to PATH")


def clear_token_cache() -> None:
    """Drop the cached ADC token (used by tests and after auth changes)."""
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0


def get_token() -> str:
    now = time.monotonic()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]
    try:
        result = subprocess.run(
            [find_gcloud(), "auth", "application-default", "print-access-token"],
            capture_output=True, text=True, timeout=GCLOUD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"gcloud print-access-token timed out after {GCLOUD_TIMEOUT_SECONDS}s"
        )
    if result.returncode != 0:
        # Raise instead of sys.exit (#423): a transient gcloud failure must fail
        # this one tool call, not kill the whole MCP server.
        raise RuntimeError(
            "No valid gcloud credentials (run: gcloud auth application-default login). "
            f"gcloud stderr: {result.stderr.strip()}"
        )
    token = result.stdout.strip()
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + TOKEN_CACHE_TTL_SECONDS
    return token


def _is_rate_limit_envelope(resp: Any) -> bool:
    if not isinstance(resp, dict):
        return False
    err = resp.get("error")
    return isinstance(err, dict) and err.get("code") == 429


def api(method: str, url: str, data: Optional[Dict] = None) -> Dict:
    last_resp: Dict = {}
    for attempt in range(API_MAX_ATTEMPTS):
        token = get_token()
        cmd = [
            "curl", "-s",
            "--connect-timeout", str(CURL_CONNECT_TIMEOUT_SECONDS),
            "--max-time", str(CURL_MAX_TIME_SECONDS),
            "-X", method, url,
            "-H", f"Authorization: Bearer {token}",
            "-H", f"x-goog-user-project: {QUOTA_PROJECT}",
            "-H", "Content-Type: application/json",
        ]
        if data:
            cmd.extend(["-d", json.dumps(data)])
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=CURL_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"curl timed out after {CURL_SUBPROCESS_TIMEOUT_SECONDS}s: {method} {url}"
            )
        if result.returncode != 0:
            raise RuntimeError(f"curl failed: {result.stderr}")
        try:
            last_resp = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw": result.stdout}
        if _is_rate_limit_envelope(last_resp) and attempt < API_MAX_ATTEMPTS - 1:
            time.sleep(API_BACKOFF_BASE_SECONDS * (2 ** attempt))
            continue
        return last_resp
    return last_resp


def _fetch_authed_bytes(url: str):
    """Fetch raw bytes from a URL using the same gcloud ADC credentials as api().

    Returns a (bytes, str) tuple of (image_bytes, mime_type).
    The mime_type is extracted from the HTTP Content-Type response header.
    Follows redirects (-L) since Google contentUri values typically 302-redirect.
    Headers are written to a temp file to avoid in-band interference with binary payload.
    """
    import tempfile
    import os as _os

    token = get_token()

    # Write headers to a temp file; image bytes go to stdout as binary.
    with tempfile.NamedTemporaryFile(delete=False, suffix=".headers") as hf:
        header_path = hf.name

    try:
        cmd = [
            "curl", "-sL",
            "--connect-timeout", str(CURL_CONNECT_TIMEOUT_SECONDS),
            "--max-time", str(CURL_MAX_TIME_SECONDS),
            "-D", header_path,
            "-H", f"Authorization: Bearer {token}",
            "-H", f"x-goog-user-project: {QUOTA_PROJECT}",
            url,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=CURL_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"curl timed out after {CURL_SUBPROCESS_TIMEOUT_SECONDS}s fetching image: {url}"
            )
        if result.returncode != 0:
            raise RuntimeError(f"curl failed fetching image: {result.stderr.decode('utf-8', errors='replace')}")

        # Parse mime type from headers
        mime_type = "application/octet-stream"
        try:
            with open(header_path, "r", errors="replace") as hfile:
                for line in hfile:
                    lower = line.lower()
                    if lower.startswith("content-type:"):
                        ct = line.split(":", 1)[1].strip()
                        # Strip charset or boundary params: "image/png; charset=utf-8" -> "image/png"
                        # No break — scan all headers so the final response's Content-Type wins
                        # (curl -D dumps headers from every hop in the redirect chain)
                        mime_type = ct.split(";")[0].strip()
        except OSError:
            pass

        return result.stdout, mime_type
    finally:
        try:
            _os.unlink(header_path)
        except OSError:
            pass


def multipart_upload(upload_url: str, metadata: Dict, file_bytes: bytes, mime_type: str) -> Dict:
    """Upload a file via Drive multipart upload using stdlib urllib.

    Sends a multipart/related body with:
      - Part 1: file metadata (JSON)
      - Part 2: file bytes (binary)

    Returns the parsed JSON response from the Drive API.
    """
    import urllib.error
    import urllib.request

    token = get_token()
    boundary = "gdocs_mcp_boundary_12345"
    content_type = f"multipart/related; boundary={boundary}"

    meta_json = json.dumps(metadata).encode("utf-8")
    body_parts = (
        f"--{boundary}\r\n"
        f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
    ).encode("utf-8") + meta_json + (
        f"\r\n--{boundary}\r\n"
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--".encode("utf-8")

    req = urllib.request.Request(
        upload_url,
        data=body_parts,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Goog-User-Project": QUOTA_PROJECT,
            "Content-Type": content_type,
            "Content-Length": str(len(body_parts)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=CURL_MAX_TIME_SECONDS) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": f"HTTP {e.code}: {body}"}
