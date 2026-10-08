"""Inventory and classify every Omnigent session into one triage state.

Offline-testable: the classifier is a pure function over the session records the
server already returns. Feed it live data (``--server``), a saved JSON file
(``--input``), or stdin (``--input -``). Nothing here mutates a session.

    uv run --no-project python fleet_report.py --server http://127.0.0.1:6767
    uv run --no-project python fleet_report.py --input fleet.json --json

Why a cascade and not the raw ``status`` field: the server's ``status`` is a
lifecycle flag, not a health verdict. ``idle`` is both "finished the turn" and
"never started" (#974); ``runner_online: true`` says the runner has a tunnel, not
that the agent is doing anything; a session that stopped to ask a permission
question sits in ``idle`` forever with nowhere to render it (#972). Each rule
below reads more than one field precisely because every single field lies.

Cascade (first match wins), modelled on Agent Orchestrator's ``determineStatus``:

    failed status ............................. dead
    pending elicitation ....................... needs_input
    running ................................... working
    idle + runner offline ..................... parked      (finished, or died quietly)
    idle + runner online + seed-only history .. stuck       (created, never woken)
    idle + runner online + stale > threshold .. stale       (probably done, unconfirmed)
    idle + runner online + last msg is a question .. needs_input   (#1800)
    idle + runner online + dirty/unpushed workspace .. stale       (#1800, WIP)
    idle + runner online, recently active ..... done_candidate

The last two exist because ``done_candidate`` was measurably too optimistic
(#1800): a session blocked on an AWS SSO login and a session with 4 uncommitted
files both classified as candidates to verify-and-close. Neither field is on the
coarse list, so both checks read data an enrichment step attaches — see
``merge_info`` and ``probe_workspace_git``.

The classifier never emits ``done``. Completion is a PR URL, a commit SHA, or a
green gate — never a status field (#971). It reports a *candidate* and the human
(or the skill) confirms against the artifact.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Iterable

#: Triage states, urgent first. The report prints in this order so the top of the
#: output is what needs a human now (Agent Orchestrator's urgent/action/warning/info).
STATES: tuple[str, ...] = (
    "dead",
    "needs_input",
    "stuck",
    "stale",
    "working",
    "done_candidate",
    "parked",
)

PRIORITY: dict[str, str] = {
    "dead": "urgent",
    "needs_input": "urgent",
    "stuck": "urgent",
    "stale": "warning",
    "working": "info",
    "done_candidate": "action",
    "parked": "info",
}

#: A session idle for longer than this with a live runner is "stale": either the
#: agent finished and nobody harvested the result, or it wedged without a pending
#: elicitation. Either way a human should look. 30 minutes is a starting point;
#: tune from the friction log, not from taste.
DEFAULT_STALE_SECONDS = 30 * 60

#: History item types that prove an agent actually did something. A history holding
#: only the user's seed message and resource events is *not* liveness
#: (dispatch-launch/liveness-and-surfacing.md).
WORK_ITEM_TYPES = frozenset({"function_call", "function_call_output", "tool_call", "tool_result"})

#: Fields a ``sys_session_get_info`` read supersedes on a coarse ``sys_session_list``
#: row. ``get_info`` is the fresher and more specific read, so on a conflict it wins
#: — and the conflict is recorded rather than silently resolved (#1800).
INFO_FIELDS: tuple[str, ...] = (
    "status",
    "runner_online",
    "last_activity_at",
    "workspace",
    "pending_elicitation_count",
    "pending_elicitations",
    "parent_session_id",
    "host_id",
    "labels",
    "items",
    "title",
    "agent_name",
)

#: Phrases that mark a turn that ended by handing control back to a human. A
#: session whose last assistant message matches one is waiting on you, whatever
#: `pending_elicitation_count` says — the real case was an AWS SSO login (#1800).
#:
#: Tuned deliberately loose: a false positive costs one human glance, a false
#: negative closes a session that was mid-question. Those are not symmetric.
AWAITING_HUMAN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b(?:waiting|blocked)\s+(?:on|for)\s+(?:you|your)\b", "says it is waiting on you"),
    (r"\bawaiting\s+(?:you|your)\b", "says it is awaiting you"),
    (r"\bneed\s+you\s+to\b", "asks you to do something"),
    (r"\blet\s+me\s+know\b", "asks you to report back"),
    (r"\b(?:can|could|would)\s+you\b", "asks you a direct question"),
    (r"\bplease\s+(?:run|confirm|approve|log\s?in|authenticate|check|provide|paste)\b", "asks you to act"),
    (r"\bonce\s+you(?:'ve|\s+have)\b", "is gated on something you do"),
    (r"\b(?:do|would)\s+you\s+want\b", "asks you to choose"),
    (r"\bshould\s+I\b", "asks you to decide"),
    (r"\byour\s+go-?ahead\b", "wants your go-ahead"),
)

#: Optional probe attached to a record before classification, shape:
#: ``{"dirty_files": 4, "branch": "x", "upstream": None, "ahead": 2, "pr": None}``.
#: Absent means "not probed" — never "clean". The classifier must not infer a clean
#: tree from missing data; that inference is what #1800 is about.
WORKSPACE_GIT_FIELD = "workspace_git"


@dataclass
class Verdict:
    session_id: str
    title: str
    agent: str
    state: str
    priority: str
    reason: str
    status: str
    runner_online: bool | None
    idle_seconds: int | None
    workspace: str | None = None
    parent_session_id: str | None = None
    host_id: str | None = None
    labels: dict[str, str] = field(default_factory=dict)
    #: Set when the coarse list and `get_info` disagreed on `status`. Reported as a
    #: fact in the row instead of being silently resolved (#1800).
    status_mismatch: str | None = None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _has_real_work(items: Iterable[dict[str, Any]] | None) -> bool | None:
    """True if history shows tool activity, False if seed-only, None if unknown."""
    if items is None:
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") in WORK_ITEM_TYPES:
            return True
        if item.get("type") == "message" and item.get("role") == "assistant":
            return True
    return False


def _item_text(item: dict[str, Any]) -> str:
    """Best-effort plain text of one history item, across the shapes seen in the wild."""
    content = item.get("content")
    if isinstance(content, str):
        return content
    parts: list[str] = []
    if isinstance(content, list):
        for chunk in content:
            if isinstance(chunk, str):
                parts.append(chunk)
            elif isinstance(chunk, dict):
                text = chunk.get("text") or chunk.get("value")
                if isinstance(text, str):
                    parts.append(text)
    for key in ("text", "message", "summary"):
        value = item.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts)


def awaiting_human(items: Iterable[dict[str, Any]] | None) -> str | None:
    """Why the last assistant message looks like a handoff to a human, or None.

    `pending_elicitation_count` only catches a *structured* elicitation. A session
    that simply ended its turn with "can you log into AWS SSO and tell me when
    you're done?" has no pending elicitation and reads as a finished turn (#1800).
    The prose is the only evidence there is, so read it.
    """
    if items is None:
        return None
    last = None
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message" and item.get("role") == "assistant":
            last = item
    if last is None:
        return None
    text = _item_text(last).strip()
    if not text:
        return None
    for pattern, why in AWAITING_HUMAN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return why
    if text.rstrip("`*_ \t\n").endswith("?"):
        return "ends on a question"
    return None


def workspace_wip(session: dict[str, Any]) -> str | None:
    """Why this session's workspace still holds unfinished work, or None.

    Reads the optional `workspace_git` probe. Missing probe → None: unknown is not
    clean. A dirty tree, or a branch that was never pushed, or commits ahead with no
    PR, is WIP — not a candidate to verify-and-close (#1800: 4 uncommitted files).
    """
    probe = session.get(WORKSPACE_GIT_FIELD)
    if not isinstance(probe, dict) or probe.get("error"):
        return None
    reasons: list[str] = []
    dirty = _int_or_none(probe.get("dirty_files"))
    if dirty:
        reasons.append(f"{dirty} uncommitted file(s)")
    has_pr = bool(probe.get("pr"))
    if "upstream" in probe and not probe.get("upstream") and not has_pr:
        branch = probe.get("branch") or "the branch"
        reasons.append(f"{branch} was never pushed (no upstream, so no PR)")
    ahead = _int_or_none(probe.get("ahead"))
    if ahead and not has_pr:
        reasons.append(f"{ahead} unpushed commit(s) and no PR")
    return "; ".join(reasons) or None


def probe_workspace_git(
    workspace: str,
    *,
    run: Callable[[list[str]], tuple[int, str]] | None = None,
) -> dict[str, Any]:
    """Local `git` facts for one workspace. Three cheap reads, no network, no `gh`.

    A branch with no upstream cannot have a PR, which is why this needs no `gh`
    call to answer "unpushed with no PR". Injectable `run` keeps the classifier's
    tests process-free.
    """
    runner = run or _run_git
    probe: dict[str, Any] = {"workspace": workspace}
    code, out = runner(["git", "-C", workspace, "status", "--short"])
    if code != 0:
        return {**probe, "error": out.strip() or f"git status exited {code}"}
    probe["dirty_files"] = len([line for line in out.splitlines() if line.strip()])
    code, out = runner(["git", "-C", workspace, "rev-parse", "--abbrev-ref", "HEAD"])
    probe["branch"] = out.strip() if code == 0 else None
    code, out = runner(
        ["git", "-C", workspace, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]
    )
    probe["upstream"] = out.strip() if code == 0 and out.strip() else None
    if probe["upstream"]:
        code, out = runner(["git", "-C", workspace, "rev-list", "--count", "@{u}..HEAD"])
        probe["ahead"] = _int_or_none(out.strip()) if code == 0 else None
    return probe


def _run_git(argv: list[str]) -> tuple[int, str]:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=20)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return done.returncode, done.stdout if done.returncode == 0 else (done.stderr or done.stdout)


def merge_info(row: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """Merge a `sys_session_get_info` read over a coarse `sys_session_list` row.

    `get_info` wins on every conflict — it is the fresher, more specific read. A
    `status` conflict is recorded in `status_mismatch` so the row can report it as a
    fact: a list saying `failed` while `get_info` says `idle` is real signal about
    the server, not noise to hide (#1800).
    """
    merged = dict(row)
    for key in INFO_FIELDS:
        value = info.get(key)
        if key in info and value is not None:
            merged[key] = value
    list_status = row.get("status")
    info_status = info.get("status")
    if list_status and info_status and str(list_status) != str(info_status):
        merged["status_mismatch"] = f"list={list_status} get_info={info_status}"
    return merged


def index_info(payload: Any) -> dict[str, dict[str, Any]]:
    """Index `sys_session_get_info` results by session id, from any of its shapes.

    Accepts a list of info objects, a mapping of session id → info object, or a
    single info object. One of them is whatever your harness happened to save.
    """
    records: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        for key in ("data", "sessions", "info"):
            if isinstance(payload.get(key), list):
                records = [r for r in payload[key] if isinstance(r, dict)]
                break
        else:
            if any(isinstance(v, dict) for v in payload.values()):
                return {
                    str(k): dict(v) for k, v in payload.items() if isinstance(v, dict)
                }
            records = [payload]
    elif isinstance(payload, list):
        records = [r for r in payload if isinstance(r, dict)]
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        sid = record.get("session_id") or record.get("id") or record.get("conversation_id")
        if sid:
            indexed[str(sid)] = record
    return indexed


def merge_info_all(
    sessions: Iterable[dict[str, Any]], info_by_id: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Apply `merge_info` to every row that has an enrichment read available."""
    merged = []
    for row in sessions:
        sid = str(row.get("session_id") or row.get("id") or "")
        info = info_by_id.get(sid)
        merged.append(merge_info(row, info) if info else dict(row))
    return merged


def needs_workspace_probe(session: dict[str, Any]) -> bool:
    """Only rows whose verdict can actually turn on git state get probed.

    Keeps the enrichment bounded (#1688's risk): an `idle` + live-runner row with a
    workspace is the only shape where `done_candidate` could be hiding WIP.
    """
    return bool(
        session.get("workspace")
        and str(session.get("status") or "") == "idle"
        and session.get("runner_online") is True
        and WORKSPACE_GIT_FIELD not in session
    )


def attach_workspace_git(
    sessions: Iterable[dict[str, Any]],
    *,
    probe: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Attach a `workspace_git` probe to the rows that need one, and only those."""
    prober = probe or (lambda ws: probe_workspace_git(ws))
    out = []
    for row in sessions:
        row = dict(row)
        if needs_workspace_probe(row):
            row[WORKSPACE_GIT_FIELD] = prober(str(row["workspace"]))
        out.append(row)
    return out


def classify(
    session: dict[str, Any],
    *,
    now: float | None = None,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> Verdict:
    """Map one session record to a triage state. Pure; safe to unit-test."""
    now = time.time() if now is None else now
    status = str(session.get("status") or "unknown")
    runner_online = session.get("runner_online")
    last = _int_or_none(session.get("last_activity_at"))
    idle = int(now - last) if last is not None else None
    pending = session.get("pending_elicitation_count")
    if pending is None:
        pending = len(session.get("pending_elicitations") or [])
    work = _has_real_work(session.get("items"))

    base = dict(
        session_id=str(session.get("session_id") or session.get("id") or "?"),
        title=str(session.get("title") or "(untitled)"),
        agent=str(session.get("agent_name") or session.get("agent") or "?"),
        status=status,
        runner_online=runner_online if isinstance(runner_online, bool) else None,
        idle_seconds=idle,
        workspace=session.get("workspace"),
        parent_session_id=session.get("parent_session_id"),
        host_id=session.get("host_id"),
        labels=dict(session.get("labels") or {}),
        status_mismatch=session.get("status_mismatch"),
    )

    def verdict(state: str, reason: str) -> Verdict:
        if base["status_mismatch"]:
            reason = (
                f"{reason} — NOTE: the coarse list and get_info disagree "
                f"({base['status_mismatch']}); get_info is the fresher read and wins"
            )
        return Verdict(state=state, priority=PRIORITY[state], reason=reason, **base)

    if status == "failed":
        return verdict("dead", "status=failed; relaunch in place, do not delete the worktree")
    if pending:
        return verdict("needs_input", f"{pending} pending elicitation(s); it is waiting on a human, not thinking")
    if status == "running":
        return verdict("working", "status=running")
    if status == "idle":
        if runner_online is False or runner_online is None:
            return verdict("parked", "idle with no live runner; finished or died quietly — confirm against the artifact")
        if work is False:
            return verdict("stuck", "idle + runner online + seed-only history: created, never woken (#974)")
        if idle is not None and idle > stale_seconds:
            return verdict("stale", f"idle {idle // 60}m with a live runner and no pending question; look at it")
        waiting = awaiting_human(session.get("items"))
        if waiting:
            return verdict(
                "needs_input",
                f"no structured elicitation, but its last message {waiting}: it is "
                "waiting on a human, not finished (#1800)",
            )
        wip = workspace_wip(session)
        if wip:
            return verdict(
                "stale",
                f"looks like a finished turn, but the workspace says WIP — {wip}. "
                "Not a candidate to verify-and-close (#1800)",
            )
        if idle is None:
            return verdict(
                "done_candidate",
                "idle with a live runner, but this row has no last_activity_at: "
                "UNENRICHED, so the verdict is a guess — merge sys_session_get_info "
                "(--info) before trusting it",
            )
        return verdict("done_candidate", "idle recently with a live runner; a turn just finished — verify the artifact, not the status")
    return verdict("stale", f"unrecognised status={status!r}; treat as needing eyes (api_shape_drift?)")


def classify_all(sessions: Iterable[dict[str, Any]], **kw: Any) -> list[Verdict]:
    verdicts = [classify(s, **kw) for s in sessions]
    order = {s: i for i, s in enumerate(STATES)}
    verdicts.sort(key=lambda v: (order[v.state], -(v.idle_seconds or 0)))
    return verdicts


def fetch_sessions(server: str, timeout: float = 15.0) -> list[dict[str, Any]]:
    """GET /v1/sessions from a local Omnigent server. No auth header: loopback only."""
    url = server.rstrip("/") + "/v1/sessions"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 - loopback URL
            payload = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"fleet_report: cannot read {url}: {exc}") from exc
    return _unwrap(payload)


def _unwrap(payload: Any) -> list[dict[str, Any]]:
    """Accept ``{"data": [...]}``, ``{"sessions": [...]}``, or a bare list."""
    if isinstance(payload, dict):
        for key in ("data", "sessions"):
            if isinstance(payload.get(key), list):
                return payload[key]
        raise SystemExit("fleet_report: payload has no 'data' or 'sessions' list (api_shape_drift — log it)")
    if isinstance(payload, list):
        return payload
    raise SystemExit(f"fleet_report: unexpected payload type {type(payload).__name__}")


def render(verdicts: list[Verdict], *, include_parked: bool) -> str:
    lines: list[str] = []
    counts = {s: 0 for s in STATES}
    for v in verdicts:
        counts[v.state] += 1
    summary = "  ".join(f"{s}={counts[s]}" for s in STATES if counts[s])
    lines.append(f"fleet: {len(verdicts)} sessions  {summary}")
    lines.append("")
    current = None
    for v in verdicts:
        if v.state == "parked" and not include_parked:
            continue
        if v.state != current:
            current = v.state
            lines.append(f"## {v.state} ({v.priority})")
        idle = "" if v.idle_seconds is None else f" idle={v.idle_seconds // 60}m"
        parent = " child" if v.parent_session_id else ""
        lines.append(f"- {v.session_id}  [{v.agent}]{parent}{idle}  {v.title}")
        lines.append(f"    {v.reason}")
    if not include_parked and counts["parked"]:
        lines.append("")
        lines.append(f"({counts['parked']} parked sessions hidden; --all to show)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--server", help="Omnigent server base URL, e.g. http://127.0.0.1:6767")
    src.add_argument("--input", help="JSON file with sessions (or '-' for stdin)")
    ap.add_argument(
        "--info",
        help="JSON file of sys_session_get_info reads (list, or map of session_id → info); "
        "merged over the coarse rows, which is how a remote pass recovers "
        "last_activity_at and workspace",
    )
    ap.add_argument(
        "--workspace-git",
        action="store_true",
        help="run git status/upstream checks on idle live-runner rows that have a "
        "workspace, so WIP is not reported as done_candidate",
    )
    ap.add_argument("--json", action="store_true", help="emit machine-readable verdicts")
    ap.add_argument("--all", action="store_true", help="include parked sessions in the text report")
    ap.add_argument("--stale-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    args = ap.parse_args(argv)

    if args.info == "-" and args.input == "-":
        ap.error("--input and --info cannot both read stdin; stage one as a file")

    if args.input:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        sessions = _unwrap(json.loads(raw))
    elif args.server:
        sessions = fetch_sessions(args.server)
    else:
        ap.error("one of --server or --input is required")

    if args.info:
        info_raw = sys.stdin.read() if args.info == "-" else open(args.info, encoding="utf-8").read()
        sessions = merge_info_all(sessions, index_info(json.loads(info_raw)))
    if args.workspace_git:
        sessions = attach_workspace_git(sessions)

    verdicts = classify_all(sessions, stale_seconds=args.stale_seconds)
    if args.json:
        print(json.dumps([asdict(v) for v in verdicts], indent=1))
    else:
        print(render(verdicts, include_parked=args.all))
    return 0


if __name__ == "__main__":
    sys.exit(main())
