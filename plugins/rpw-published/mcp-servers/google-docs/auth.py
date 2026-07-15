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
import sys
from typing import Dict, Optional

from config import QUOTA_PROJECT


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
    print("ERROR: gcloud not found", file=sys.stderr)
    sys.exit(1)


def get_token() -> str:
    result = subprocess.run(
        [find_gcloud(), "auth", "application-default", "print-access-token"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("ERROR: No valid gcloud credentials. Run google_auth.py login", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def api(method: str, url: str, data: Optional[Dict] = None) -> Dict:
    token = get_token()
    cmd = [
        "curl", "-s", "-X", method, url,
        "-H", f"Authorization: Bearer {token}",
        "-H", f"x-goog-user-project: {QUOTA_PROJECT}",
        "-H", "Content-Type: application/json",
    ]
    if data:
        cmd.extend(["-d", json.dumps(data)])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"curl failed: {result.stderr}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw": result.stdout}


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
            "-D", header_path,
            "-H", f"Authorization: Bearer {token}",
            "-H", f"x-goog-user-project: {QUOTA_PROJECT}",
            url,
        ]
        result = subprocess.run(cmd, capture_output=True)
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
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": f"HTTP {e.code}: {body}"}
