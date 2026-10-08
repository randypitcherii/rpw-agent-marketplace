"""Post-write house-style gate (#2001): normalize the written tab, then lint it.

Every content write tool (``gdocs_create``, ``gdocs_update``, ``gdocs_add_tab``,
``gdocs_write_to_tab``) calls ``apply`` after a successful write. The tool result
then carries a compact ``style`` summary, and a tab that still fails the lint
turns the result into an error. An agent can trust the formatting without reading
the doc back.

``gdocs_find_replace`` is not gated. ``replaceAllText`` keeps the style of the text
it replaces, so it adds no formatting of its own. A doc-wide replace would also
make the gate restyle every tab in the doc, including tabs the agent never wrote.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import auth
import style_lint
import style_normalize

BATCH_SIZE = 50
SUMMARY_SAMPLES = 5
DOC_URL = "https://docs.googleapis.com/v1/documents/{doc_id}"


def _get(doc_id: str) -> Dict[str, Any]:
    return auth.raise_for_error(auth.api("GET", DOC_URL.format(doc_id=doc_id) + "?includeTabsContent=true"))


def _first_tab_id(document: Dict[str, Any]) -> Optional[str]:
    tabs = document.get("tabs") or []
    return (tabs[0].get("tabProperties") or {}).get("tabId") if tabs else None


def summarize(result: Dict[str, Any]) -> Dict[str, Any]:
    """Shrink a lint result to what a write tool returns: counts plus a few locators."""
    samples: List[str] = []
    for v in result["violations"]:
        if len(samples) >= SUMMARY_SAMPLES:
            break
        where = v["samples"][0] if v["samples"] else ""
        samples.append(f"{v['rule']} ({v['severity']}): expected {v['expected']}, got {v['actual']}"
                       f" ×{v['count']} @ {where}")
    return {"ok": result["ok"], "errors": result["errors"], "warnings": result["warnings"],
            "by_rule": result["by_rule"], "samples": samples}


def apply(doc_id: str, tab_id: Optional[str] = None) -> Dict[str, Any]:
    """Normalize one tab (default: the first) to the house style, then lint it.

    Returns ``{ok, errors, warnings, by_rule, samples, tabId, normalized}``. On an API
    failure returns ``{ok: False, error, tabId, normalized, batchesCompleted}``;
    ``normalized`` is the number of requests planned.
    """
    planned = 0
    done = 0
    try:
        document = _get(doc_id)
        tab_id = tab_id or _first_tab_id(document)
        requests = style_normalize.normalize_requests(document, tab_id=tab_id)
        planned = len(requests)
        # Order matters (index-changing deletions run last), so batches are sequential.
        for i in range(0, len(requests), BATCH_SIZE):
            auth.raise_for_error(auth.api("POST", DOC_URL.format(doc_id=doc_id) + ":batchUpdate",
                                          {"requests": requests[i:i + BATCH_SIZE]}))
            done += 1
        result = style_lint.lint_document(_get(doc_id) if requests else document, tab_id=tab_id)
    except (auth.DocsApiError, ValueError) as e:
        return {"ok": False, "tabId": tab_id, "normalized": planned, "batchesCompleted": done,
                "error": f"house-style normalize failed: {e}"}
    return {**summarize(result), "tabId": tab_id, "normalized": planned}


def gate(out: Dict[str, Any], doc_id: str, tab_id: Optional[str] = None) -> Dict[str, Any]:
    """Attach the style result to a successful write envelope; fail it if the tab is off-style.

    The content write already happened, so a failure keeps the envelope's ids and url,
    appends ``_but_style_check_failed`` to the status, and sets ``error``.
    """
    style = apply(doc_id, tab_id)
    out = dict(out, style=style)
    if not style["ok"]:
        out["status"] = f"{out.get('status', 'written')}_but_style_check_failed"
        out["error"] = style.get("error") or (
            f"Content was written, but {style['errors']} house-style error(s) remain after "
            f"normalize: {'; '.join(style['samples'][:3])}")
    return out
