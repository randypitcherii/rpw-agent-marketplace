"""The chief-of-staff friction log: record a snag now, harvest the pattern later.

Every time the chief-of-staff loop hits something that cost a human's attention —
a probe that lied, a bulk operation that turned into a hand-rolled loop, an API
that changed shape — one line lands in a local JSONL journal. Nothing is analysed
at write time (zero cost, deterministic, like claude-adam's hook). ``report``
clusters the journal by event type and names the classes that have crossed the
harvest threshold; ``self-improvement.md`` says what to do with those.

    uv run --no-project python friction_log.py log probe_lied --detail "idle+runner_online read as done" \\
        --session 324460068597277 --lesson "check history before status" \\
        --skill omnigent-chief-of-staff
    uv run --no-project python friction_log.py report
    uv run --no-project python friction_log.py report --json
    uv run --no-project python friction_log.py archive probe_lied

Journal: ``~/.rpw/chief-of-staff/friction.jsonl`` (override with ``$RPW_FRICTION_LOG``).
Archive: ``friction.actioned.jsonl`` beside it.

Two rules are enforced here rather than in prose because prose does not fail a test:

* **Closed vocabulary.** An event type outside ``EVENT_TYPES`` is rejected. A free-text
  type field turns into fifty spellings of the same headache and nothing ever clusters.
* **No secrets.** A detail or lesson that looks like a token, key, or bearer header is
  refused before it touches disk. The journal is plain text that later gets pasted
  into GitHub issues.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

#: The closed event vocabulary. Add a type here *and* in self-improvement.md; the test
#: pins both. ``safety_intentional`` is the inverse of friction (claude-skill-iterate):
#: a guardrail fired as designed. Harvest must never propose relaxing one of those.
EVENT_TYPES: dict[str, str] = {
    "probe_lied": "a status/health signal said one thing and the session was doing another",
    "bulk_op_manual_loop": "an action over N sessions had to be hand-rolled one at a time",
    "api_shape_drift": "a server response or tool result no longer matched what the skill expects",
    "rename_refused": "a title change was rejected (60-char cap, title_changed, 4xx)",
    "reconnect_failed": "a nudge/wake/attach did not revive the session",
    "user_correction": "the human corrected the chief-of-staff's read of the fleet",
    "missing_context": "the skill had to go read something it should have carried",
    "safety_intentional": "a guardrail stopped an action and that was the right call",
}

#: A house skill directory name, as it appears under ``plugins/*/skills/``. Pinned here
#: so ``--skill`` refuses a title or a slash command at write time rather than writing a
#: ``skill:`` line the usage reader will drop (#1960).
SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{2,60}$")

#: A class at or above this many *distinct* events becomes a harvest candidate.
DEFAULT_THRESHOLD = 3

#: Only the last N days count toward the threshold: stale friction should not
#: accumulate forever (claude-adam's per-signal windows, collapsed to one).
DEFAULT_WINDOW_DAYS = 30

_SECRET_PATTERNS = (
    re.compile(r"\b(?:token|apikey|api[_-]?key|secret|password)\s*[:=]\s*\S{8,}", re.I),
    re.compile(r"\bbearer\s+[A-Za-z0-9_\-.=]{12,}", re.I),
    re.compile(r"\b(?:dapi|ghp_|gho_|ghu_|github_pat_|sk-|xox[abpr]-)[A-Za-z0-9_\-]{12,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    re.compile(r"\brunner_token_[a-f0-9]{16,}\b"),  # omnigent runner credentials
)


class FrictionError(ValueError):
    """Raised for a rejected event: unknown type or secret-shaped text."""


def default_path() -> Path:
    override = os.environ.get("RPW_FRICTION_LOG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".rpw" / "chief-of-staff" / "friction.jsonl"


def archive_path(journal: Path) -> Path:
    return journal.with_name(journal.stem + ".actioned.jsonl")


def looks_like_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


def normalize_skills(values: Iterable[str] | None) -> list[str]:
    """Skill directory names from repeated ``--skill`` values, deduped in order.

    Shape-validated against ``SKILL_NAME`` rather than trusted: the harvest writes these
    into a ``skill:`` issue line that a reader parses (#1960), and a title, a slash
    command, or a plugin-qualified name would be silently dropped there. Rejecting the
    wrong shape at write time makes the mistake visible while the human is still here.
    """
    out: list[str] = []
    for raw in values or ():
        # `str(None)` is "none", which is shape-valid and would silently become a skill
        # named "none" in the harvest's `skill:` line. Skip non-strings before coercing.
        if not isinstance(raw, str):
            continue
        name = raw.strip().strip("`'\"").lower()
        if not name:
            continue
        if not SKILL_NAME.fullmatch(name):
            raise FrictionError(
                f"--skill {raw!r} is not a skill directory name; use the lowercase "
                "directory under plugins/*/skills/ (e.g. omnigent-chief-of-staff)"
            )
        if name not in out:
            out.append(name)
    return out


def make_event(
    event_type: str,
    detail: str,
    *,
    session: str | None = None,
    lesson: str | None = None,
    surface: str | None = None,
    skills: Iterable[str] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Validate and build one journal entry (no I/O)."""
    if event_type not in EVENT_TYPES:
        known = ", ".join(sorted(EVENT_TYPES))
        raise FrictionError(f"unknown event type {event_type!r}; one of: {known}")
    detail = detail.strip()
    if not detail:
        raise FrictionError("detail is required: say what happened in one line")
    for label, value in (("detail", detail), ("lesson", lesson or ""), ("surface", surface or "")):
        if looks_like_secret(value):
            raise FrictionError(f"{label} looks like it carries a credential; refusing to journal it")
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now if now is not None else time.time()))
    event: dict[str, Any] = {"ts": ts, "type": event_type, "detail": detail}
    if session:
        event["session"] = session
    if surface:
        event["surface"] = surface
    if lesson:
        event["lesson"] = lesson.strip()
    names = normalize_skills(skills)
    if names:
        event["skills"] = names
    return event


def append(event: dict[str, Any], journal: Path) -> None:
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def read(journal: Path) -> list[dict[str, Any]]:
    if not journal.exists():
        return []
    events: list[dict[str, Any]] = []
    with journal.open(encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                events.append({"ts": "", "type": "_corrupt", "detail": f"line {n} unparseable"})
    return events


def _parse_ts(ts: str) -> float | None:
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    except (ValueError, TypeError):
        return None


def cluster(
    events: Iterable[dict[str, Any]],
    *,
    threshold: int = DEFAULT_THRESHOLD,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: float | None = None,
) -> dict[str, Any]:
    """Group events by type inside the window; flag classes at/over threshold."""
    now = time.time() if now is None else now
    cutoff = now - window_days * 86400
    in_window: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dropped = 0
    corrupt = 0
    for ev in events:
        if ev.get("type") == "_corrupt":
            corrupt += 1
            continue
        t = _parse_ts(ev.get("ts", ""))
        if t is None or t < cutoff:
            dropped += 1
            continue
        in_window[str(ev.get("type"))].append(ev)

    classes = []
    for etype, evs in sorted(in_window.items(), key=lambda kv: -len(kv[1])):
        lessons = Counter(e.get("lesson") for e in evs if e.get("lesson"))
        # Most-implicated first (#1960): the harvest writes one `skill:` line per name,
        # and the order is the order a reader should read them in.
        skills = Counter(
            name for e in evs for name in (e.get("skills") or []) if isinstance(name, str)
        )
        classes.append(
            {
                "type": etype,
                "count": len(evs),
                "harvest": etype != "safety_intentional" and len(evs) >= threshold,
                "guardrail": etype == "safety_intentional",
                "first": min(e["ts"] for e in evs),
                "last": max(e["ts"] for e in evs),
                "sessions": sorted({e["session"] for e in evs if e.get("session")}),
                "top_lessons": [l for l, _ in lessons.most_common(3)],
                "skills": [name for name, _ in skills.most_common()],
                "details": [e["detail"] for e in evs][-5:],
            }
        )
    return {
        "window_days": window_days,
        "threshold": threshold,
        "in_window": sum(len(v) for v in in_window.values()),
        "outside_window": dropped,
        "corrupt": corrupt,
        "classes": classes,
        "harvest": [c["type"] for c in classes if c["harvest"]],
    }


def render(report: dict[str, Any]) -> str:
    out = [
        f"friction: {report['in_window']} events in the last {report['window_days']}d "
        f"({report['outside_window']} older ignored, {report['corrupt']} corrupt)",
        f"harvest threshold: {report['threshold']}",
        "",
    ]
    if not report["classes"]:
        out.append("(journal is empty in this window — good, or nobody is logging)")
        return "\n".join(out)
    for c in report["classes"]:
        flag = "HARVEST" if c["harvest"] else ("guardrail" if c["guardrail"] else "watch")
        out.append(f"## {c['type']}  x{c['count']}  [{flag}]  {c['first'][:10]} → {c['last'][:10]}")
        for d in c["details"]:
            out.append(f"  - {d}")
        if c["top_lessons"]:
            out.append("  lessons: " + " | ".join(c["top_lessons"]))
        # Printed as the ready-to-paste `skill:` line(s) the harvest issue needs (#1960).
        for name in c.get("skills", []):
            out.append(f"  skill: {name}")
        if c["sessions"]:
            out.append("  sessions: " + ", ".join(c["sessions"][:6]))
        out.append("")
    if report["harvest"]:
        out.append("HARVEST: " + ", ".join(report["harvest"]) + " — follow self-improvement.md")
    return "\n".join(out)


def archive(journal: Path, types: Iterable[str]) -> int:
    """Move every active event of the given types into the actioned archive."""
    types = set(types)
    events = read(journal)
    keep = [e for e in events if e.get("type") not in types]
    moved = [e for e in events if e.get("type") in types]
    if not moved:
        return 0
    with archive_path(journal).open("a", encoding="utf-8") as fh:
        for e in moved:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    with journal.open("w", encoding="utf-8") as fh:
        for e in keep:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return len(moved)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--journal", type=Path, default=None, help="override the journal path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_log = sub.add_parser("log", help="append one friction event")
    p_log.add_argument("type", choices=sorted(EVENT_TYPES))
    p_log.add_argument("--detail", required=True, help="one line: what happened")
    p_log.add_argument("--session", help="session id it happened on")
    p_log.add_argument("--surface", help="which tool/route lied: sys_session_get_info, PATCH /v1/sessions, ...")
    p_log.add_argument("--lesson", help="one line: what you would tell the skill to do differently")
    p_log.add_argument(
        "--skill",
        action="append",
        default=[],
        metavar="NAME",
        help="house skill this snag implicates (repeatable; directory name under "
        "plugins/*/skills/). Omit when no skill is at fault.",
    )

    p_rep = sub.add_parser("report", help="cluster the journal and flag harvest candidates")
    p_rep.add_argument("--json", action="store_true")
    p_rep.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    p_rep.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)

    p_arc = sub.add_parser("archive", help="move harvested event types to the actioned archive")
    p_arc.add_argument("types", nargs="+", choices=sorted(EVENT_TYPES))

    sub.add_parser("types", help="print the event vocabulary")

    args = ap.parse_args(argv)
    journal = args.journal or default_path()

    if args.cmd == "types":
        for k, v in EVENT_TYPES.items():
            print(f"{k:22} {v}")
        return 0
    if args.cmd == "log":
        try:
            ev = make_event(
                args.type,
                args.detail,
                session=args.session,
                lesson=args.lesson,
                surface=args.surface,
                skills=args.skill,
            )
        except FrictionError as exc:
            print(f"friction_log: {exc}", file=sys.stderr)
            return 2
        append(ev, journal)
        print(f"logged {ev['type']} -> {journal}")
        return 0
    if args.cmd == "report":
        rep = cluster(read(journal), threshold=args.threshold, window_days=args.window_days)
        print(json.dumps(rep, indent=1) if args.json else render(rep))
        return 0
    if args.cmd == "archive":
        n = archive(journal, args.types)
        print(f"archived {n} event(s) -> {archive_path(journal)}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
