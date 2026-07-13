#!/usr/bin/env python3
"""Jira MCP server — FastMCP over a Databricks UC HTTP-proxy connection (http_request)."""

import json
import sys
from pathlib import Path
from typing import Any

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod
from fastmcp import FastMCP

from lib import uc_proxy_client

mcp = FastMCP(name="jira-uc-mcp")


def _parse_method(method: str) -> ExternalFunctionRequestHttpMethod:
    normalized = method.strip().upper()
    try:
        return ExternalFunctionRequestHttpMethod[normalized]
    except KeyError as exc:
        raise ValueError("method must be one of GET, POST, PUT, PATCH, DELETE") from exc


def _adf_paragraph(text: str) -> dict[str, Any]:
    """Wrap plain text in Atlassian Document Format (required for description/comment bodies)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": text}]}
        ],
    }


# --- Tools ---


@mcp.tool
def jira_search(
    jql: str,
    fields: str = "summary,status,assignee,priority,created",
    max_results: int = 25,
) -> str:
    """Search Jira issues with JQL (Jira Query Language).

    fields: comma-separated field list (e.g. 'summary,status,assignee'). Use '*all' for everything.
    max_results: clamped to 1..100.
    """
    field_list = (
        [f.strip() for f in fields.split(",") if f.strip()]
        if fields and fields != "*all"
        else ["*all"]
    )
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.POST,
        "search/jql",
        json_body={
            "jql": jql,
            "fields": field_list,
            "maxResults": min(max(max_results, 1), 100),
        },
    )


@mcp.tool
def jira_get_issue(key: str, fields: str = "*all") -> str:
    """Get a Jira issue by key (e.g. ABC-123). fields is comma-separated; default '*all'."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        f"issue/{key}",
        query_params={"fields": fields},
    )


@mcp.tool
def jira_create_issue(
    project_key: str,
    summary: str,
    issue_type: str = "Task",
    description: str = "",
) -> str:
    """Create a new Jira issue. description is plain text (auto-wrapped in ADF)."""
    fields: dict[str, Any] = {
        "project": {"key": project_key},
        "summary": summary,
        "issuetype": {"name": issue_type},
    }
    if description:
        fields["description"] = _adf_paragraph(description)
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.POST,
        "issue",
        json_body={"fields": fields},
    )


@mcp.tool
def jira_add_comment(key: str, body: str) -> str:
    """Add a comment to a Jira issue. body is plain text (auto-wrapped in ADF)."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.POST,
        f"issue/{key}/comment",
        json_body={"body": _adf_paragraph(body)},
    )


@mcp.tool
def jira_get_transitions(key: str) -> str:
    """List available transitions for a Jira issue. Use to find transition IDs for jira_transition_issue."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        f"issue/{key}/transitions",
    )


@mcp.tool
def jira_transition_issue(key: str, transition_id: str) -> str:
    """Transition a Jira issue to a new state. Look up transition_id with jira_get_transitions first."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.POST,
        f"issue/{key}/transitions",
        json_body={"transition": {"id": transition_id}},
    )


@mcp.tool
def jira_list_projects() -> str:
    """List all Jira projects the user can access."""
    return uc_proxy_client.request_via_env(
        ExternalFunctionRequestHttpMethod.GET,
        "project",
    )


@mcp.tool
def jira_api_request(path: str, method: str = "GET", payload_json: str = "{}") -> str:
    """Escape hatch: call any Jira REST v3 endpoint. path is relative to /rest/api/3/.
    payload_json is parsed and used as the JSON body for non-GET methods.
    """
    try:
        parsed_method = _parse_method(method)
        payload = json.loads(payload_json or "{}")
        if not isinstance(payload, dict):
            return json.dumps({"ok": False, "error": "payload_json must decode to an object"})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})
    if parsed_method == ExternalFunctionRequestHttpMethod.GET:
        return uc_proxy_client.request_via_env(parsed_method, path)
    return uc_proxy_client.request_via_env(parsed_method, path, json_body=payload)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
