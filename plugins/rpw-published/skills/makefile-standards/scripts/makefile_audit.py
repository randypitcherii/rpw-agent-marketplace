#!/usr/bin/env python3
"""Mechanical inventory of a GNU Makefile: targets, .PHONY gaps, help gaps, recipe size.

Read-only. Stdlib only. Run with: uv run --no-project python makefile_audit.py [Makefile]

Prints one TSV row per explicit target, then a summary, and ends with a single
`outcome=` line:

  outcome=clean     every target is .PHONY (or a real file) and carries `## ` help,
                    and no .PHONY name lacks a rule
  outcome=gaps      at least one of those three gaps was found
  outcome=unreadable the Makefile could not be read

Columns: target, line, recipe_lines, phony (y/n), inline_help (y/n), in_help_list (y/n),
inline_code (python/heredoc/-).

"Recipe lines" counts physical lines, so a 1-line target with 40 backslash continuations
counts 41 -- that is the size a reader has to hold, which is what the threshold is about.
"In help list" means the name appears in the recipe of the `help` target, for Makefiles
whose help is a hand-written echo list rather than generated from `## ` comments.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TARGET_RE = re.compile(r"^([A-Za-z0-9_.%/$(){}-][A-Za-z0-9_.%/$(){} -]*?)\s*:(?![=:])(.*)$")
ASSIGN_RE = re.compile(r"^\s*(export\s+)?[A-Za-z0-9_.-]+\s*(:=|\?=|\+=|=|::=)")


def parse(text: str):
    lines = text.splitlines()
    targets: dict[str, dict] = {}
    phony: set[str] = set()
    current: list[dict] = []
    in_define = False
    continuing = False
    for idx, raw in enumerate(lines, start=1):
        if in_define:
            if raw.strip() == "endef":
                in_define = False
            continue
        if raw.startswith("define ") or raw.startswith("export define "):
            in_define = True
            current = []
            continue
        if raw.startswith("\t"):
            for t in current:
                t["recipe"].append(raw)
            continuing = raw.endswith("\\")
            continue
        if continuing and current:
            for t in current:
                t["recipe"].append(raw)
            continuing = raw.endswith("\\")
            continue
        continuing = False
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith(".PHONY"):
            phony.update(raw.split(":", 1)[1].split())
            current = []
            continue
        if ASSIGN_RE.match(raw):
            current = []
            continue
        m = TARGET_RE.match(raw)
        if not m or raw.startswith((".", "ifeq", "ifneq", "ifdef", "ifndef", "else", "endif", "include", "-include")):
            current = []
            continue
        names = m.group(1).split()
        rest = m.group(2)
        inline_help = "##" in rest
        # `name: VAR := value` is a target-specific variable, not a rule.
        if ASSIGN_RE.match(rest.strip() + " "):
            current = []
            continue
        current = []
        for name in names:
            if "%" in name or "$" in name:
                continue
            entry = targets.setdefault(
                name, {"line": idx, "recipe": [], "help": False}
            )
            entry["help"] = entry["help"] or inline_help
            current.append(entry)
    return targets, phony


def inline_code(recipe: list[str]) -> str:
    body = "\n".join(recipe)
    kinds = []
    if re.search(r"python3?\s+-c\b|python3?\s+-\s|python3?\s+<<|uv run[^\n]*python[^\n]*-c\b", body):
        kinds.append("python")
    if re.search(r"<<(?!<)", body):
        kinds.append("heredoc")
    return ",".join(kinds) or "-"


def main(argv: list[str]) -> int:
    path = Path(argv[1] if len(argv) > 1 else "Makefile")
    try:
        text = path.read_text()
    except OSError as exc:
        print(f"error: {exc}")
        print("outcome=unreadable")
        return 2
    targets, phony = parse(text)
    help_body = "\n".join(targets.get("help", {}).get("recipe", []))
    # A help generated from `## ` text (it reads $(MAKEFILE_LIST)) lists every
    # documented target by construction, so there is no hand list to compare.
    if "MAKEFILE_LIST" in help_body:
        help_body = ""
    rows = []
    for name, t in sorted(targets.items(), key=lambda kv: kv[1]["line"]):
        in_list = bool(re.search(rf"make {re.escape(name)}(\s|\"|$)", help_body))
        rows.append(
            (name, t["line"], len(t["recipe"]), name in phony, t["help"], in_list, inline_code(t["recipe"]))
        )
    print("target\tline\trecipe_lines\tphony\tinline_help\tin_help_list\tinline_code")
    for r in rows:
        print("\t".join([r[0], str(r[1]), str(r[2]), "y" if r[3] else "n", "y" if r[4] else "n", "y" if r[5] else "n", r[6]]))
    not_phony = [r[0] for r in rows if not r[3] and not Path(path.parent, r[0]).exists()]
    # `## ` on the rule line is the convention; a hand-written help list is not a
    # substitute, so it is reported separately and never counts as documentation.
    undocumented = [r[0] for r in rows if not r[4]]
    unlisted = [r[0] for r in rows if not r[5]] if help_body else []
    stale_phony = sorted(p for p in phony if p not in targets)
    print(f"\ntargets={len(rows)} phony_declared={len(phony)}")
    print(f"missing_phony={len(not_phony)}: {' '.join(not_phony)}")
    print(f"undocumented={len(undocumented)}: {' '.join(undocumented)}")
    print(f"phony_without_rule={len(stale_phony)}: {' '.join(stale_phony)}")
    if help_body:
        print(f"absent_from_help_recipe={len(unlisted)} (informational): {' '.join(unlisted)}")
    print("outcome=gaps" if not_phony or undocumented or stale_phony else "outcome=clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
