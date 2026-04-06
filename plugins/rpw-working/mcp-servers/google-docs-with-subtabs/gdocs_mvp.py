#!/usr/bin/env python3
"""
Google Docs MVP — CRUD operations scoped to a specific Drive folder.

Uses gcloud ADC auth (same as vibe's google-tools).

Operations:
  create   - Create a new doc from markdown in the target folder
  list     - List docs in the target folder
  read     - Read a doc's content (plain text)
  update   - Append markdown content to an existing doc
  delete   - Trash a doc
  add-tab  - Add a sub-tab (named tab) to a doc

Usage:
  uv run python gdocs_mvp.py create --title "My Doc" --content "# Hello\n\nWorld"
  uv run python gdocs_mvp.py list
  uv run python gdocs_mvp.py read --doc-id DOC_ID
  uv run python gdocs_mvp.py update --doc-id DOC_ID --content "## New Section\n\nMore text"
  uv run python gdocs_mvp.py delete --doc-id DOC_ID
  uv run python gdocs_mvp.py add-tab --doc-id DOC_ID --tab-name "Notes" --content "# Notes\n\nSome notes"
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from typing import Optional, Dict, List, Any

# ============================================================================
# CONFIG — Change this folder ID to scope all operations
# ============================================================================
TARGET_FOLDER_ID = os.environ.get("GDOCS_TARGET_FOLDER_ID", "1p66DzOuAGYzPvX4eJGa3VWeTvUB4dalW")
QUOTA_PROJECT = os.environ.get("GDOCS_QUOTA_PROJECT", "your-gcp-project-id")


# ============================================================================
# AUTH HELPERS
# ============================================================================

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


# ============================================================================
# CORE OPERATIONS
# ============================================================================

def create_doc(title: str, content: Optional[str] = None) -> Dict:
    """Create a new Google Doc in the target folder."""
    # Step 1: Create the doc via Docs API
    resp = api("POST", "https://docs.googleapis.com/v1/documents", {"title": title})
    if "error" in resp:
        return resp
    doc_id = resp["documentId"]

    # Step 2: Move it into the target folder via Drive API
    token = get_token()
    # Get current parent
    file_info = api("GET", f"https://www.googleapis.com/drive/v3/files/{doc_id}?fields=parents")
    current_parents = ",".join(file_info.get("parents", []))

    # Move to target folder
    move_cmd = [
        "curl", "-s", "-X", "PATCH",
        f"https://www.googleapis.com/drive/v3/files/{doc_id}?addParents={TARGET_FOLDER_ID}&removeParents={current_parents}",
        "-H", f"Authorization: Bearer {token}",
        "-H", f"x-goog-user-project: {QUOTA_PROJECT}",
        "-H", "Content-Type: application/json",
    ]
    subprocess.run(move_cmd, capture_output=True, text=True)

    # Step 3: Add content if provided
    if content:
        _insert_markdown(doc_id, content, index=1)

    return {
        "documentId": doc_id,
        "title": title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def list_docs() -> List[Dict]:
    """List all Google Docs in the target folder."""
    url = (
        f"https://www.googleapis.com/drive/v3/files"
        f"?q='{TARGET_FOLDER_ID}'+in+parents+and+mimeType='application/vnd.google-apps.document'+and+trashed=false"
        f"&fields=files(id,name,modifiedTime,webViewLink)"
        f"&orderBy=modifiedTime+desc"
        f"&pageSize=50"
    )
    resp = api("GET", url)
    return resp.get("files", [])


def read_doc(doc_id: str) -> Dict:
    """Read a document's content as plain text, including all tabs."""
    # Use includeTabsContent to get tab info
    resp = api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}?includeTabsContent=true")
    if "error" in resp:
        return resp

    result = {
        "documentId": doc_id,
        "title": resp.get("title", ""),
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
        "tabs": [],
    }

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
            # Extract text from tab body
            body = tab.get("documentTab", {}).get("body", {})
            for element in body.get("content", []):
                if "paragraph" in element:
                    for pe in element["paragraph"].get("elements", []):
                        if "textRun" in pe:
                            tab_info["text"] += pe["textRun"].get("content", "")
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
        full_text = ""
        for element in body.get("content", []):
            if "paragraph" in element:
                for pe in element["paragraph"].get("elements", []):
                    if "textRun" in pe:
                        full_text += pe["textRun"].get("content", "")
        result["text"] = full_text

    return result


def update_doc(doc_id: str, content: str) -> Dict:
    """Append markdown-ish content to the end of a document."""
    # Get end index
    resp = api("GET", f"https://docs.googleapis.com/v1/documents/{doc_id}")
    if "error" in resp:
        return resp
    body_content = resp.get("body", {}).get("content", [])
    end_index = body_content[-1].get("endIndex", 1) - 1 if body_content else 1

    _insert_markdown(doc_id, content, index=end_index)
    return {
        "status": "updated",
        "documentId": doc_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def delete_doc(doc_id: str) -> Dict:
    """Trash a document (soft delete)."""
    resp = api(
        "PATCH",
        f"https://www.googleapis.com/drive/v3/files/{doc_id}",
        {"trashed": True},
    )
    if "error" in resp:
        return resp
    return {"status": "trashed", "documentId": doc_id}


def add_tab(doc_id: str, tab_name: str, content: Optional[str] = None,
            parent_tab_id: Optional[str] = None, icon_emoji: Optional[str] = None) -> Dict:
    """Add a named tab (or sub-tab if parent_tab_id is given) to a Google Doc."""
    tab_props: Dict[str, Any] = {"title": tab_name}
    if parent_tab_id:
        tab_props["parentTabId"] = parent_tab_id
    if icon_emoji:
        tab_props["iconEmoji"] = icon_emoji

    requests = [
        {
            "addDocumentTab": {
                "tabProperties": tab_props,
            }
        }
    ]
    resp = api(
        "POST",
        f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
        {"requests": requests},
    )
    if "error" in resp:
        return resp

    # Extract the new tab ID from the response
    new_tab_id = None
    replies = resp.get("replies", [])
    for reply in replies:
        if "addDocumentTab" in reply:
            new_tab_id = reply["addDocumentTab"].get("tabProperties", {}).get("tabId")
            break

    result = {
        "status": "tab_added",
        "documentId": doc_id,
        "tabName": tab_name,
        "tabId": new_tab_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }

    # Add content to the new tab if provided
    if content and new_tab_id:
        _insert_markdown(doc_id, content, index=1, tab_id=new_tab_id)

    return result


# ============================================================================
# MARKDOWN INSERTION HELPER
# ============================================================================

def _insert_markdown(doc_id: str, content: str, index: int = 1, tab_id: Optional[str] = None):
    """Insert text content into a doc at the given index, with basic formatting."""
    lines = content.strip().split("\n")
    requests = []
    current_index = index

    for line in lines:
        text = line.rstrip()
        heading_level = 0

        # Detect headings
        if text.startswith("######"):
            heading_level = 6; text = text[6:].strip()
        elif text.startswith("#####"):
            heading_level = 5; text = text[5:].strip()
        elif text.startswith("####"):
            heading_level = 4; text = text[4:].strip()
        elif text.startswith("###"):
            heading_level = 3; text = text[3:].strip()
        elif text.startswith("##"):
            heading_level = 2; text = text[2:].strip()
        elif text.startswith("#"):
            heading_level = 1; text = text[1:].strip()

        insert_text = text + "\n"

        # Build location (with optional tab targeting)
        location = {"index": current_index}
        if tab_id:
            location["tabId"] = tab_id

        requests.append({
            "insertText": {
                "location": location,
                "text": insert_text,
            }
        })

        end_index = current_index + len(insert_text)

        if heading_level > 0:
            rng = {"startIndex": current_index, "endIndex": end_index}
            if tab_id:
                rng["tabId"] = tab_id
            requests.append({
                "updateParagraphStyle": {
                    "range": rng,
                    "paragraphStyle": {"namedStyleType": f"HEADING_{heading_level}"},
                    "fields": "namedStyleType",
                }
            })

        # Handle bold: **text**
        import re
        bold_pattern = re.compile(r'\*\*(.+?)\*\*')
        for match in bold_pattern.finditer(text):
            bold_start = current_index + match.start()
            bold_end = current_index + match.end()
            rng = {"startIndex": bold_start, "endIndex": bold_end}
            if tab_id:
                rng["tabId"] = tab_id
            requests.append({
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })

        current_index = end_index

    # Execute in batches of 50
    for i in range(0, len(requests), 50):
        batch = requests[i:i + 50]
        api(
            "POST",
            f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
            {"requests": batch},
        )


def find_replace(doc_id: str, find_text: str, replace_text: str,
                 match_case: bool = False, tab_id: Optional[str] = None) -> Dict:
    """Replace all occurrences of find_text with replace_text in a doc (optionally in a tab)."""
    req: Dict[str, Any] = {
        "replaceAllText": {
            "containsText": {"text": find_text, "matchCase": match_case},
            "replaceText": replace_text,
        }
    }
    if tab_id:
        req["replaceAllText"]["tabId"] = tab_id
    resp = api(
        "POST",
        f"https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate",
        {"requests": [req]},
    )
    if "error" in resp:
        return resp
    count = resp.get("replies", [{}])[0].get("replaceAllText", {}).get("occurrencesChanged", 0)
    return {
        "status": "replaced",
        "documentId": doc_id,
        "occurrencesChanged": count,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def write_to_tab(doc_id: str, tab_id: str, content: str) -> Dict:
    """Insert markdown content at the start of a specific tab."""
    _insert_markdown(doc_id, content, index=1, tab_id=tab_id)
    return {
        "status": "written",
        "documentId": doc_id,
        "tabId": tab_id,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Google Docs MVP — CRUD + tabs, scoped to a Drive folder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p = sub.add_parser("create", help="Create a new doc")
    p.add_argument("--title", "-t", required=True)
    p.add_argument("--content", "-c", default=None, help="Markdown content")
    p.add_argument("--file", "-f", default=None, help="Read content from file")

    # list
    sub.add_parser("list", help="List docs in target folder")

    # read
    p = sub.add_parser("read", help="Read a doc")
    p.add_argument("--doc-id", "-d", required=True)

    # update
    p = sub.add_parser("update", help="Append content to a doc")
    p.add_argument("--doc-id", "-d", required=True)
    p.add_argument("--content", "-c", default=None)
    p.add_argument("--file", "-f", default=None, help="Read content from file")

    # delete
    p = sub.add_parser("delete", help="Trash a doc")
    p.add_argument("--doc-id", "-d", required=True)

    # add-tab
    p = sub.add_parser("add-tab", help="Add a tab (or sub-tab) to a doc")
    p.add_argument("--doc-id", "-d", required=True)
    p.add_argument("--tab-name", "-n", required=True)
    p.add_argument("--parent-tab-id", "-p", default=None, help="Parent tab ID to nest under")
    p.add_argument("--icon", default=None, help="Emoji icon for the tab")
    p.add_argument("--content", "-c", default=None)
    p.add_argument("--file", "-f", default=None, help="Read content from file")

    args = parser.parse_args()

    try:
        if args.command == "create":
            content = args.content
            if args.file:
                with open(args.file) as f:
                    content = f.read()
            result = create_doc(args.title, content)

        elif args.command == "list":
            result = list_docs()

        elif args.command == "read":
            result = read_doc(args.doc_id)

        elif args.command == "update":
            content = args.content
            if args.file:
                with open(args.file) as f:
                    content = f.read()
            if not content:
                print("ERROR: --content or --file required", file=sys.stderr)
                sys.exit(1)
            result = update_doc(args.doc_id, content)

        elif args.command == "delete":
            result = delete_doc(args.doc_id)

        elif args.command == "add-tab":
            content = args.content
            if args.file:
                with open(args.file) as f:
                    content = f.read()
            result = add_tab(args.doc_id, args.tab_name, content,
                            parent_tab_id=args.parent_tab_id,
                            icon_emoji=args.icon)

        print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
