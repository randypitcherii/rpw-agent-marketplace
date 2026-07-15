"""
Read-path operations for the Google Docs MCP server.

``list_docs`` (Drive folder listing), ``read_doc`` (plain-text + tab + inline-
image extraction), and ``get_image_bytes`` (authed inline-image fetch). All
network calls go through ``auth`` (module-qualified so tests patch a single
point). ``TARGET_FOLDER_ID`` is read from ``config`` at call time.
"""

from typing import Any, Dict, List

import auth
import config


def list_docs() -> List[Dict]:
    """List all Google Docs in the target folder."""
    if not config.TARGET_FOLDER_ID:
        raise RuntimeError(
            "GDOCS_TARGET_FOLDER_ID is not set — set the env var or use run_mcp.py for env-file resolution"
        )
    url = (
        f"https://www.googleapis.com/drive/v3/files"
        f"?q='{config.TARGET_FOLDER_ID}'+in+parents+and+mimeType='application/vnd.google-apps.document'+and+trashed=false"
        f"&fields=files(id,name,modifiedTime,webViewLink)"
        f"&orderBy=modifiedTime+desc"
        f"&pageSize=50"
    )
    resp = auth.api("GET", url)
    return resp.get("files", [])


def read_doc(doc_id: str) -> Dict:
    """Read a document's content as plain text, including all tabs."""
    # Use includeTabsContent to get tab info
    resp = auth.api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true")
    if "error" in resp:
        return resp

    # Build inlineObjects map. When the API is called with includeTabsContent=true (which
    # we always do), inlineObjects lives PER-TAB at tab.documentTab.inlineObjects, NOT at
    # the top level. We collect from both for defense in depth + to keep existing test
    # mocks (which use the top-level shape) compatible.
    inline_objects_map: Dict[str, Any] = {}

    def _record_inline_objects(raw: Dict[str, Any]) -> None:
        for obj_id, obj in raw.items():
            if obj_id in inline_objects_map:
                continue  # first occurrence wins
            embedded = obj.get("inlineObjectProperties", {}).get("embeddedObject", {})
            image_props = embedded.get("imageProperties", {})
            size = embedded.get("size", {})
            width = size.get("width", {}).get("magnitude")
            height = size.get("height", {}).get("magnitude")
            inline_objects_map[obj_id] = {
                "uri": image_props.get("contentUri"),
                "mimeType": None,
                "width": width,
                "height": height,
                "description": embedded.get("description"),
                "title": embedded.get("title"),
            }

    _record_inline_objects(resp.get("inlineObjects", {}))

    result = {
        "documentId": doc_id,
        "title": resp.get("title", ""),
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        "tabs": [],
        "inlineObjects": inline_objects_map,
    }

    def _elements_to_text(elements) -> str:
        """Convert paragraph elements to text, including [image: <id>] placeholders."""
        text = ""
        for pe in elements:
            if "textRun" in pe:
                text += pe["textRun"].get("content", "")
            elif "inlineObjectElement" in pe:
                obj_id = pe["inlineObjectElement"].get("inlineObjectId", "")
                text += f"[image: {obj_id}]"
        return text

    def _table_cell_to_text(cell: Dict[str, Any]) -> str:
        """Extract readable text from a table cell, including nested rich content."""
        return _body_content_to_text(cell.get("content", [])).strip()

    def _table_to_text(table: Dict[str, Any]) -> str:
        """Render a Docs table as tab-separated rows for the plain-text read path."""
        rows: List[str] = []
        for row in table.get("tableRows", []):
            cells = [
                _table_cell_to_text(cell)
                for cell in row.get("tableCells", [])
            ]
            rows.append("\t".join(cells).rstrip())
        return "\n".join(rows) + ("\n" if rows else "")

    def _body_content_to_text(content: List[Dict[str, Any]]) -> str:
        text = ""
        for element in content:
            if "paragraph" in element:
                text += _elements_to_text(
                    element["paragraph"].get("elements", [])
                )
            elif "table" in element:
                text += _table_to_text(element["table"])
        return text

    # Extract tabs (recursively to handle child/sub-tabs)
    def extract_tabs(tabs_list, depth=0):
        extracted = []
        for tab in tabs_list:
            tab_props = tab.get("tabProperties", {})
            tab_info = {
                "tabId": tab_props.get("tabId", ""),
                "title": tab_props.get("title", ""),
                "index": tab_props.get("index", 0),
                "nestingLevel": depth,
                "parentTabId": tab_props.get("parentTabId", ""),
                "text": "",
                "childTabs": [],
            }
            # Collect this tab's inlineObjects into the result map (live API shape).
            document_tab = tab.get("documentTab", {})
            _record_inline_objects(document_tab.get("inlineObjects", {}))
            # Extract text from tab body (including image placeholders)
            body = document_tab.get("body", {})
            tab_info["text"] += _body_content_to_text(body.get("content", []))
            # Recurse into child tabs
            children = tab.get("childTabs", [])
            if children:
                tab_info["childTabs"] = extract_tabs(children, depth + 1)
            extracted.append(tab_info)
        return extracted

    result["tabs"] = extract_tabs(resp.get("tabs", []))

    # Also get flat text from default body (for docs without explicit tabs)
    body = resp.get("body", {})
    if body:
        result["text"] = _body_content_to_text(body.get("content", []))

    return result


def get_image_bytes(doc_id: str, object_id: str) -> Dict:
    """Fetch the raw bytes of an inline image in a Google Doc, base64-encoded.

    Returns: { documentId, objectId, mimeType, data } where data is base64.
    On missing objectId or missing contentUri: { status: "not_found", ... }.
    """
    import base64

    # Use includeTabsContent=true so we see inlineObjects nested in tab.documentTab
    # AND the top-level (for docs without explicit tabs). Search both locations.
    resp = auth.api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true")
    if "error" in resp:
        return resp

    inline_objects: Dict[str, Any] = {}
    inline_objects.update(resp.get("inlineObjects", {}))

    def _collect(tabs_list):
        for tab in tabs_list:
            inline_objects.update(tab.get("documentTab", {}).get("inlineObjects", {}))
            _collect(tab.get("childTabs", []))

    _collect(resp.get("tabs", []))

    if object_id not in inline_objects:
        return {"status": "not_found", "documentId": doc_id, "objectId": object_id}

    embedded = (
        inline_objects[object_id]
        .get("inlineObjectProperties", {})
        .get("embeddedObject", {})
    )
    content_uri = embedded.get("imageProperties", {}).get("contentUri")
    if not content_uri:
        return {"status": "not_found", "documentId": doc_id, "objectId": object_id}

    img_bytes, mime_type = auth._fetch_authed_bytes(content_uri)
    return {
        "documentId": doc_id,
        "objectId": object_id,
        "mimeType": mime_type,
        "data": base64.b64encode(img_bytes).decode("ascii"),
    }
