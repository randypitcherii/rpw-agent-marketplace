#!/usr/bin/env python3
"""Gmail MCP server — FastMCP over a Databricks UC HTTP-proxy connection.

Exposes the Gmail v1 API surface only. Drive (including the `about` identity
endpoint), Calendar, Tasks, and Docs each have dedicated sibling servers.
"""

import base64
import sys
from email.message import EmailMessage
from pathlib import Path

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod
from fastmcp import FastMCP

from lib import uc_proxy_client

mcp = FastMCP(name="google-gmail-uc-mcp")


# --- Gmail ---


@mcp.tool
def google_gmail_search(query: str, max_results: int = 25) -> str:
    """Search Gmail messages with Gmail search syntax (e.g. "from:foo@bar.com newer_than:7d").

    Returns message id/threadId pairs only — call google_gmail_get_message for details.
    max_results clamped to 1..100.
    """
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        "gmail/v1/users/me/messages",
        query_params={
            "q": query,
            "maxResults": str(min(max(max_results, 1), 100)),
        },
    )


@mcp.tool
def google_gmail_get_message(message_id: str, format: str = "metadata") -> str:
    """Get a Gmail message by ID. format: 'metadata' (headers only), 'full' (with payload), 'minimal', 'raw'."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        f"gmail/v1/users/me/messages/{message_id}",
        query_params={"format": format},
    )


@mcp.tool
def google_gmail_send(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> str:
    """Send an email via Gmail. to/cc/bcc accept comma-separated addresses."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.POST,
        "gmail/v1/users/me/messages/send",
        json_body={"raw": raw},
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
