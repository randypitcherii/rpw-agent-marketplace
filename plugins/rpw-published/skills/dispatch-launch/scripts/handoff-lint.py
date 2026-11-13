# /// script
# requires-python = ">=3.10"
# ///
"""Lint a dispatch completion handoff (completion-handoff.md, #2343).

Checks shape and internal consistency only. It cannot know whether the artifact
state is true; the author must have checked it. Exit 0 complete, 1 problems.
"""
from __future__ import annotations

import re
import sys

FIELDS = ("Status", "Artifact", "Tests/CI", "Deploy", "Decisions needed",
          "Scheduled/follow-on", "Cleanup")
STATUSES = {"✅": "done", "🟡": "partial", "⛔": "blocked"}
OVERCLAIM = re.compile(r"\b(shipped|fixed|complete[d]?|all done)\b", re.I)


def parse(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*[-*]?\s*\**(" + "|".join(map(re.escape, (*FIELDS, "Not done"))) + r")\**\s*:\s*(.*)$", line)
        if m:
            found[m[1]] = m[2].strip()
    return found


def lint(text: str) -> list[str]:
    f = parse(text)
    problems = [f"missing field: {name}" for name in FIELDS if not f.get(name)]
    status = next((v for k, v in STATUSES.items() if k in f.get("Status", "")), None)
    if "Status" in f and status is None:
        problems.append("Status must start with ✅ done, 🟡 partial or ⛔ blocked")
    artifact = f.get("Artifact", "").lower()
    if artifact and not re.search(r"\b(merged|open|none)\b", artifact):
        problems.append("Artifact must say its verified state: merged, open or none")
    if status == "done":
        if not re.search(r"\bmerged\b", artifact):
            problems.append("✅ done needs an artifact whose state is merged")
        if re.search(r"\bnot run\b|\bfail", f.get("Tests/CI", ""), re.I) or not f.get("Tests/CI"):
            problems.append("✅ done needs a green gate in Tests/CI")
        if re.search(r"\bpartial\b", f.get("Deploy", ""), re.I):
            problems.append("✅ done cannot carry a partial deploy")
    if status in ("partial", "blocked"):
        if not f.get("Not done"):
            problems.append(f"{status} needs a Not done line: what remains and who owns it")
        if OVERCLAIM.search(f.get("Artifact", "") + " " + f.get("Not done", "")) and "merged" not in artifact:
            problems.append(f"{status} must not use completion words about an unmerged artifact")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: handoff-lint.py <file|->", file=sys.stderr)
        return 64
    text = sys.stdin.read() if argv[1] == "-" else open(argv[1], encoding="utf-8").read()
    problems = lint(text)
    for p in problems:
        print(f"handoff: {p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
