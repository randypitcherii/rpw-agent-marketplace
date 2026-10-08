#!/usr/bin/env python3
"""Embed the morning-prep project icon into the report HTML as a base64 data URI.

A morning prep report is a local file opened straight from disk: there is no
server to own `/favicon.ico`, and a relative link breaks the moment the report is
copied anywhere. So the template carries the icon inline (registered as `inline`
for `morning-prep` in `assets/project-icons/registry.json`, favicon-standards).

The icon itself is never hand-edited: `scripts/build_icons.py` builds
`assets/icon/` from `assets/project-icons/morning-prep.png`; this script only
re-embeds `assets/icon/favicon-32.png` wherever the HTML holds a
`data:image/png;base64,...` URI.

    uv run --no-project python scripts/inline_favicon.py           # rewrite in place
    uv run --no-project python scripts/inline_favicon.py --check   # exit 1 if stale

Default targets are this skill's `assets/*.html` plus, inside the rpw monorepo,
the Omnigent project mirror (`projects/omnigent/skills/morning-prep-report/assets/`).
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ICON = SKILL_DIR / "assets" / "icon" / "favicon-32.png"
DATA_URI_RE = re.compile(r"data:image/png;base64,[A-Za-z0-9+/=]*")
HTML_NAMES = ("template.html", "example-report.html")


def data_uri(icon: Path = ICON) -> str:
    return "data:image/png;base64," + base64.b64encode(icon.read_bytes()).decode("ascii")


def default_targets() -> list[Path]:
    targets = [SKILL_DIR / "assets" / name for name in HTML_NAMES]
    repo_root = SKILL_DIR.parents[2]  # plugins/<plugin>/skills/<name> -> repo root
    mirror = repo_root / "projects" / "omnigent" / "skills" / SKILL_DIR.name / "assets"
    targets += [mirror / name for name in HTML_NAMES if (mirror / name).is_file()]
    return targets


def embed(html: str, uri: str) -> str:
    return DATA_URI_RE.sub(uri, html)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="HTML files (default: skill assets + mirror)")
    parser.add_argument("--check", action="store_true", help="verify only; exit 1 when a file is stale")
    args = parser.parse_args(argv)

    uri = data_uri()
    stale: list[Path] = []
    missing: list[Path] = []
    for path in args.files or default_targets():
        html = path.read_text(encoding="utf-8")
        if not DATA_URI_RE.search(html):
            print(f"{path}: no data:image/png;base64 URI to fill", file=sys.stderr)
            missing.append(path)
            continue
        updated = embed(html, uri)
        if updated != html:
            stale.append(path)
            if not args.check:
                path.write_text(updated, encoding="utf-8")
                print(f"embedded favicon into {path}")
    if args.check and stale:
        for path in stale:
            print(f"stale favicon data URI: {path}", file=sys.stderr)
        return 1
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
