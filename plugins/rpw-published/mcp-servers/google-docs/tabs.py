"""
Tab-tree model helpers for the Google Docs MCP server.

Google Docs tabs form a tree: subtabs are nested under each tab's ``childTabs``.
Any lookup over the tree MUST recurse — a flat scan of the top-level ``tabs``
list silently misses nested sub-tabs (this bit twice before: recursive tab
lookup and #198 table fill).
"""

from typing import Dict, List, Optional


def _find_tab_by_id(tabs: List[Dict], tab_id: str) -> Optional[Dict]:
    """Recursively search a Docs tab tree for the tab matching tab_id.

    Subtabs are nested under each tab's `childTabs`, so a flat scan of top-level
    `tabs` misses them.
    """
    for tab in tabs:
        if tab.get("tabProperties", {}).get("tabId") == tab_id:
            return tab
        found = _find_tab_by_id(tab.get("childTabs", []), tab_id)
        if found is not None:
            return found
    return None
