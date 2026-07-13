#!/usr/bin/env python3
"""Google Drive MCP server — FastMCP over a Databricks UC HTTP-proxy connection.

Exposes the Drive v3 API surface (plus the drive `about` identity endpoint).
Gmail and Calendar live in sibling servers (`google-gmail`, `google-calendar`);
Tasks lives in `google-tasks`; Docs lives in `google-docs`.
"""

import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod
from fastmcp import FastMCP

from lib import uc_proxy_client

mcp = FastMCP(name="google-drive-uc-mcp")


# --- Identity / Drive ---


@mcp.tool
def google_about() -> str:
    """Get the authenticated Google user's profile (drive.about — name, email, photo)."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        "drive/v3/about",
        query_params={"fields": "user"},
    )


@mcp.tool
def google_drive_list_files(
    query: str = "",
    page_size: int = 25,
    fields: str = "files(id,name,mimeType,modifiedTime,owners(displayName,emailAddress),webViewLink),nextPageToken",
    page_token: str = "",
) -> str:
    """List/search Drive files. query is Drive search syntax (e.g. "name contains 'foo'", "mimeType='application/vnd.google-apps.folder'").

    page_size clamped to 1..100.
    """
    params: dict[str, str] = {
        "pageSize": str(min(max(page_size, 1), 100)),
        "fields": fields,
    }
    if query:
        params["q"] = query
    if page_token:
        params["pageToken"] = page_token
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        "drive/v3/files",
        query_params=params,
    )


@mcp.tool
def google_drive_get_file(
    file_id: str,
    fields: str = "id,name,mimeType,size,modifiedTime,owners(displayName,emailAddress),webViewLink,parents",
) -> str:
    """Get metadata for a single Drive file by ID.

    `fields` is a BARE `files.get` projection over the Drive File resource
    (e.g. "name,owners,modifiedTime") and is forwarded verbatim to
    `drive/v3/files/{file_id}`. Do NOT wrap it in list-style `files(...)`
    syntax — that only applies to `files.list` (see google_drive_list_files)
    and a 400 results here. The default above is a valid bare File projection.
    """
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        f"drive/v3/files/{file_id}",
        query_params={"fields": fields},
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
