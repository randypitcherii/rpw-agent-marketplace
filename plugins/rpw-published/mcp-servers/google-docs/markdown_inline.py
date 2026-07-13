"""
Inline-level markdown → Docs helpers.

Pure functions shared by the block-level renderer (``markdown_render``) for
paragraph and table-cell inline styling: UTF-16 offset arithmetic, location/
range builders, inline-token flattening, image-token detection, and the
``_walk_inlines`` style-request emitter.
"""

from typing import Any, Dict, List, Optional

from config import DEFAULT_CODE_FONT


def _utf16_len(text: str) -> int:
    """Length of `text` measured in UTF-16 code units.

    Google Docs API document offsets are UTF-16 code units, not Python code
    points. Python's `len()` counts an emoji (e.g. 🎯) as 1, but the Docs API
    counts it as 2 (a surrogate pair). Using Python `len()` for position
    arithmetic misplaces every subsequent insert by 1 per supplementary-plane
    character, which corrupts paragraph boundaries and bullet/heading styling.
    """
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


def _mk_location(idx: int, tab_id: Optional[str]) -> Dict:
    loc: Dict = {"index": idx}
    if tab_id:
        loc["tabId"] = tab_id
    return loc


def _mk_range(start: int, end: int, tab_id: Optional[str]) -> Dict:
    rng: Dict = {"startIndex": start, "endIndex": end}
    if tab_id:
        rng["tabId"] = tab_id
    return rng


def _inline_text(token) -> str:
    """Flatten an inline token tree to its plain text (no markers)."""
    t = token.get("type", "")
    if t in ("text", "codespan"):
        return token.get("raw", "")
    if t == "softbreak":
        return " "
    children = token.get("children", [])
    if children:
        return "".join(_inline_text(c) for c in children)
    return token.get("raw", "")


def _plain_text_from_children(children) -> str:
    return "".join(_inline_text(c) for c in children)


def _is_image_token(token: Dict[str, Any]) -> bool:
    return token.get("type") == "image" and bool(_image_url(token))


def _image_url(token: Dict[str, Any]) -> str:
    return token.get("attrs", {}).get("url", "") or token.get("src", "")


def _children_contain_image(children: List[Dict[str, Any]]) -> bool:
    for child in children:
        if _is_image_token(child):
            return True
        if _children_contain_image(child.get("children", [])):
            return True
    return False


def _walk_inlines(children, para_start: int, tab_id: Optional[str],
                  code_font: str = DEFAULT_CODE_FONT, bold: bool = False) -> List[Dict]:
    """Walk inline token list; return batchUpdate style requests with pre-computed indices.

    Container tokens (``strong``, ``emphasis``, ``link``) apply their own style over the
    full token range AND recurse into their children, so nested inline styles survive
    (#182). For example ``[`code`](url)`` emits both a link and a monospace-font request
    over the same range, and ``**`code`**`` emits both bold and font. The Docs API stacks
    ``updateTextStyle`` requests whose ``fields`` masks don't overlap, so styles on the
    same range compose cleanly. This is the shared path for paragraph and table-cell
    inline rendering, so the recursion closes the table-cell drop too.
    """
    requests: List[Dict] = []
    offset = 0  # offset from para_start within the paragraph's plain text

    for token in children:
        t = token.get("type", "")
        text = _inline_text(token)
        length = _utf16_len(text)
        start = para_start + offset
        rng = _mk_range(start, start + length, tab_id)

        if t == "strong":
            requests.append({
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": {"bold": True},
                    "fields": "bold",
                }
            })
            requests.extend(_walk_inlines(token.get("children", []), start, tab_id, code_font, bold=True))
        elif t == "emphasis":
            requests.append({
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": {"italic": True},
                    "fields": "italic",
                }
            })
            requests.extend(_walk_inlines(token.get("children", []), start, tab_id, code_font, bold=bold))
        elif t == "codespan":
            # weightedFontFamily.weight is Docs' source of truth for boldness: writing
            # a weightedFontFamily resets weight to 400 unless we say otherwise, which
            # clobbers the bold a parent strong applied (#182: **`code`** would render
            # monospace-but-NOT-bold). When nested in bold, carry weight 700 so the
            # codespan stays bold. Plain codespans keep the default 400 (normal).
            font: Dict[str, Any] = {"fontFamily": code_font}
            if bold:
                font["weight"] = 700
            requests.append({
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": {"weightedFontFamily": font},
                    "fields": "weightedFontFamily",
                }
            })
        elif t == "link":
            url = token.get("attrs", {}).get("url", "")
            link_children = token.get("children", [])
            link_style: Dict[str, Any] = {"link": {"url": url}}
            link_fields = "link"
            # Code hyperlinks ([`code`](url)): suppress the default link underline.
            # Docs auto-underlines links, but the underscores common in code clash with
            # it visually — the link color is enough of an affordance (#182 3d feedback).
            if any(c.get("type") == "codespan" for c in link_children):
                link_style["underline"] = False
                link_fields = "link,underline"
            requests.append({
                "updateTextStyle": {
                    "range": rng,
                    "textStyle": link_style,
                    "fields": link_fields,
                }
            })
            requests.extend(_walk_inlines(link_children, start, tab_id, code_font, bold=bold))
        # softbreak and plain text have no extra styling

        offset += length

    return requests
