"""Strip Jira REST self-description from issue payloads (#828).

Measured 2026-09-16 against the live `jira-mcp` UC connection: `jira_search` over
30 issues with the default five fields is **43,165 bytes**, and roughly 30% of it
is Jira describing its own API rather than answering the query —
`issue.self` 7.0% and `issue.expand` 6.1% at the top level, plus a `self` +
`iconUrl` pair inside every nested `status`, `priority` and `assignee`, and a
whole `statusCategory` object hanging off each `status`. `fields.status` alone
costs 13,670 bytes (41% of all field bytes) to say `"Open"`.

Jira is the one server here where a **blacklist** is right rather than a
whitelist. The `fields` argument is the caller's own projection — they name the
fields they want, including custom fields this module has never heard of — so a
whitelist would break the tool's contract the moment someone asked for
`customfield_10021`. What is safe to remove is instead a fixed set of keys that
are pure REST plumbing at every nesting level.

**The set must contain only keys that can never be a field a caller asked for.**
A deep drop cannot tell `status.description` (the boilerplate "The issue is open
and ready for the assignee to start work on it.") from `fields.description` (the
issue's body), so `description` is deliberately NOT in the set even though
including it would save another 3%. Losing an issue's description to save bytes
is the exact failure this shaping exists to avoid.
"""

from __future__ import annotations

from typing import Any

from lib.response_shaping import drop_keys_deep

# Pure Jira REST plumbing: API self-links, icon/avatar URL sets, the `expand`
# advertisement, and the status-category rollup that restates `status.name`.
# None of these can be a field name a caller passes to `fields`.
_PLUMBING_KEYS = (
    "self",
    "expand",
    "iconUrl",
    "avatarUrls",
    "avatarId",
    "entityId",
    "statusCategory",
    "hierarchyLevel",
    "scope",
)

# Identity kept per issue alongside its `fields`.
_ISSUE_IDENTITY = ("id", "key")


def _shape_issue(issue: Any) -> Any:
    """Strip plumbing from one issue, leaving `fields` otherwise exactly as asked for."""
    if not isinstance(issue, dict):
        return issue
    out: dict[str, Any] = {k: issue[k] for k in _ISSUE_IDENTITY if k in issue}
    if "fields" in issue:
        # `drop_none=False` semantics by construction: a field the caller
        # requested stays present even when Jira returned null for it, because
        # "unassigned" and "I did not ask" are different answers.
        out["fields"] = drop_keys_deep(issue["fields"], _PLUMBING_KEYS)
    for key, value in issue.items():
        if key not in out and key not in _PLUMBING_KEYS and key != "fields":
            out[key] = drop_keys_deep(value, _PLUMBING_KEYS)
    return out


def shape_search(data: dict[str, Any]) -> dict[str, Any] | None:
    """Project a `search/jql` response, or None if it is not one.

    `nextPageToken` and `isLast` are carried through under snake_case names — they
    are how a caller pages, so shaping must not swallow them.
    """
    issues = data.get("issues")
    if not isinstance(issues, list):
        return None
    out: dict[str, Any] = {
        "ok": True,
        "total": len(issues),
        "issues": [_shape_issue(i) for i in issues],
    }
    token = data.get("nextPageToken")
    if token:
        out["next_page_token"] = token
    if "isLast" in data:
        out["is_last"] = data["isLast"]
    return out


def shape_issue(data: dict[str, Any]) -> dict[str, Any] | None:
    """Project a single-issue `issue/{key}` response, or None if it is not one.

    Same plumbing strip as `shape_search`. `jira_get_issue` defaults to
    `fields="*all"`, which is the largest single-issue payload the server can
    return, so it benefits from the same treatment even though the filed issue
    named only the search tool.
    """
    if not isinstance(data.get("fields"), dict):
        return None
    shaped = _shape_issue(data)
    shaped["ok"] = True
    return shaped
