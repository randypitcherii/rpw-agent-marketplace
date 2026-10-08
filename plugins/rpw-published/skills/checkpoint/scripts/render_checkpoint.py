#!/usr/bin/env python3
"""Render a Claude Code session transcript .jsonl into a checkpoint pair.

Zero model tokens: the agent runs this and prints the two paths. Nothing about
the conversation is read into context.

  <out>/<ISO stamp>--checkpoint--INDEX.md       read this
  <out>/<ISO stamp>--checkpoint--TRANSCRIPT.md  grep this, never read whole

One read of the .jsonl produces both files. INDEX is the de-noised spine (user
prompts, assistant prose, one line per tool call); TRANSCRIPT is the full
mechanical render including tool results and sidechain (subagent) entries.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# INDEX stays readable in full: prompts and prose are the signal, but a pasted
# 40 KB log in a user turn is not. Cap per block, never per file.
PROMPT_CHARS = 1500
PROSE_CHARS = 2000
ARG_HINT_CHARS = 120

# Which input field is the useful one-line hint, per tool. First match wins.
ARG_KEYS = (
    "command", "file_path", "path", "pattern", "query", "url", "skill",
    "description", "prompt", "notebook_path", "to",
)


# --------------------------------------------------------------------------
# locating the session file
# --------------------------------------------------------------------------

def project_key(cwd: str) -> str:
    """Claude Code's project dir name: EVERY non-alphanumeric char becomes '-'.

    Not just '/': a home dir like `/Users/<you>` lands under
    `-Users--you--...`, so a naive slash-only swap misses the dir.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))


def _newest_jsonl(d: Path) -> Path | None:
    files = [p for p in d.glob("*.jsonl") if p.is_file() and p.stat().st_size > 0]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _by_recorded_cwd(cwd: str, projects_root: Path) -> Path | None:
    """Fallback: ask the transcripts themselves which one ran in this dir.

    Authoritative regardless of how the harness encodes directory names — each
    entry records its own `cwd`. Only the first few lines of each project's
    newest transcript are read, so this stays cheap.
    """
    target = str(Path(cwd).resolve())
    best = None
    for d in projects_root.iterdir():
        if not d.is_dir():
            continue
        newest = _newest_jsonl(d)
        if newest is None:
            continue
        with newest.open(encoding="utf-8", errors="replace") as fh:
            for line in (next(fh, "") for _ in range(20)):
                if '"cwd"' not in line:
                    continue
                try:
                    if json.loads(line).get("cwd") == target:
                        if best is None or newest.stat().st_mtime > best.stat().st_mtime:
                            best = newest
                        break
                except json.JSONDecodeError:
                    continue
    return best


def find_session_file(cwd: str, projects_root: Path) -> Path:
    d = projects_root / project_key(cwd)
    if d.is_dir():
        newest = _newest_jsonl(d)
        if newest is not None:
            return newest  # newest by mtime is the live session
    if projects_root.is_dir():
        found = _by_recorded_cwd(cwd, projects_root)
        if found is not None:
            return found
    raise SystemExit(
        f"no session transcript found for {Path(cwd).resolve()}\n"
        f"  looked in: {d}\n"
        f"  and scanned {projects_root} for a transcript recording that cwd\n"
        f"  pass --session-file <path.jsonl> to render a specific transcript"
    )


def load(path: Path) -> list[dict]:
    entries = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                entries.append(obj)
    return entries


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + f" …[+{len(text) - limit} chars]"


def one_line(text: str, limit: int) -> str:
    return clip(" ".join(str(text).split()), limit)


def blocks(entry: dict) -> list[dict]:
    """Normalize message content to a list of typed blocks."""
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [b for b in content if isinstance(b, dict)]
    return []


def result_text(block: dict) -> str:
    """Flatten a tool_result's content, whatever shape it arrived in."""
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for part in content:
            if isinstance(part, dict):
                out.append(part.get("text") or json.dumps(part, default=str))
            else:
                out.append(str(part))
        return "\n".join(out)
    if content is None:
        return ""
    return json.dumps(content, default=str)


def arg_hint(tool_input, base: str = "") -> str:
    """One short line naming what the call acted on."""
    if not isinstance(tool_input, dict):
        return ""
    candidates = [tool_input.get(k) for k in ARG_KEYS]
    candidates += list(tool_input.values())
    for val in candidates:
        if isinstance(val, str) and val.strip():
            # Relative beats absolute: truncation eats the tail, and the tail of a
            # path is the filename — the only part worth reading.
            if base and val.startswith(base + os.sep):
                val = val[len(base) + 1:]
            return one_line(val, ARG_HINT_CHARS)
    return ""


def is_noise_user(entry: dict, text: str) -> bool:
    """Harness bookkeeping dressed as a user turn — excluded from the INDEX."""
    if entry.get("isMeta"):
        return True
    stripped = text.strip()
    if not stripped:
        return True
    return stripped.startswith((
        "<local-command-stdout>", "<local-command-stderr>",
        "<command-message>", "Caveat: The messages below",
    ))


def git(cwd: str, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


# --------------------------------------------------------------------------
# header
# --------------------------------------------------------------------------

def gather_header(entries: list[dict], session_file: Path, cwd: str) -> dict:
    session_id = branch = transcript_cwd = ""
    first_ts = last_ts = ""
    prompts = assistant_msgs = tool_calls = tool_errors = sidechain = 0
    error_ids: set[str] = set()

    for entry in entries:
        session_id = entry.get("sessionId") or session_id
        branch = entry.get("gitBranch") or branch
        transcript_cwd = entry.get("cwd") or transcript_cwd
        ts = entry.get("timestamp")
        if isinstance(ts, str) and ts:
            first_ts = first_ts or ts
            last_ts = ts
        if entry.get("isSidechain"):
            sidechain += 1
            continue
        etype = entry.get("type")
        if etype == "assistant":
            assistant_msgs += 1
        for block in blocks(entry):
            btype = block.get("type")
            if btype == "tool_use":
                tool_calls += 1
            elif btype == "tool_result":
                if block.get("is_error"):
                    tool_errors += 1
                    error_ids.add(block.get("tool_use_id") or "")
            elif etype == "user" and btype == "text":
                if not is_noise_user(entry, block.get("text") or ""):
                    prompts += 1

    work_dir = transcript_cwd or cwd
    return {
        "session_id": session_id or session_file.stem,
        "cwd": work_dir,
        "branch": branch or git(work_dir, "rev-parse", "--abbrev-ref", "HEAD"),
        "head": git(work_dir, "log", "-1", "--format=%h %s"),
        "dirty": git(work_dir, "status", "--porcelain"),
        "first_ts": first_ts,
        "last_ts": last_ts,
        "prompts": prompts,
        "assistant_msgs": assistant_msgs,
        "tool_calls": tool_calls,
        "tool_errors": tool_errors,
        "sidechain": sidechain,
        "entries": len(entries),
        "source": str(session_file),
        "error_ids": error_ids,
    }


def header_md(h: dict, stamp: str, kind: str) -> list[str]:
    dirty = h["dirty"].splitlines()
    lines = [
        f"# Session checkpoint — {kind}",
        "",
        f"- **session** `{h['session_id']}`",
        f"- **cwd** `{h['cwd']}`",
        f"- **branch** `{h['branch'] or '(unknown)'}`",
        f"- **HEAD** {h['head'] or '(unknown)'}",
        f"- **span** {h['first_ts'] or '?'} → {h['last_ts'] or '?'}",
        f"- **turns** {h['prompts']} user prompts · {h['assistant_msgs']} assistant messages "
        f"· {h['tool_calls']} tool calls ({h['tool_errors']} failed) · {h['sidechain']} sidechain entries",
        f"- **rendered** {stamp} from `{h['source']}` ({h['entries']} entries)",
    ]
    if dirty:
        lines.append(f"- **dirty paths** ({len(dirty)}):")
        lines += [f"  - `{line}`" for line in dirty[:60]]
        if len(dirty) > 60:
            lines.append(f"  - …{len(dirty) - 60} more")
    else:
        lines.append("- **dirty paths** none (clean tree)")
    lines.append("")
    return lines


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

def render(entries: list[dict], h: dict, stamp: str) -> tuple[str, str]:
    error_ids = h["error_ids"]

    index = header_md(h, stamp, "INDEX (read this)")
    index += [
        "De-noised spine: every user prompt, assistant prose, and one line per tool call.",
        "Tool *results*, file contents, command output, diffs, and thinking are excluded by",
        f"design — grep `{stamp}--checkpoint--TRANSCRIPT.md` for a `[#NNNN]` id to see detail.",
        "",
        "---",
        "",
    ]

    transcript = header_md(h, stamp, "TRANSCRIPT (grep only — do NOT read whole)")
    transcript += [
        "**Grep target, not a reading target.** Full mechanical render of every entry",
        "including tool results and sidechain (subagent) turns. Anchors `[#NNNN]` match the",
        "INDEX; grep for one instead of loading this file.",
        "",
        "---",
        "",
    ]

    for n, entry in enumerate(entries):
        anchor = f"[#{n:04d}]"
        etype = entry.get("type")
        side = bool(entry.get("isSidechain"))
        content_blocks = blocks(entry)
        if not content_blocks:
            continue

        ts = (entry.get("timestamp") or "")[11:19]
        tag = "sidechain " if side else ""
        transcript += [f"## {anchor} {tag}{etype} {ts}".rstrip(), ""]

        for block in content_blocks:
            btype = block.get("type")

            if btype == "thinking":
                transcript += ["<details><summary>thinking</summary>", "", "```",
                               block.get("thinking") or "", "```", "", "</details>", ""]
                continue

            if btype == "tool_use":
                name = block.get("name") or "tool"
                hint = arg_hint(block.get("input"), h["cwd"])
                mark = "❌" if (block.get("id") in error_ids) else "✅"
                if not side:
                    index.append(f"- `{anchor}` {mark} **{name}**" + (f" — {hint}" if hint else ""))
                transcript += [f"**tool_use** {name} (id `{block.get('id')}`)", "", "```json",
                               json.dumps(block.get("input"), indent=2, default=str)[:20000],
                               "```", ""]
                continue

            if btype == "tool_result":
                mark = "error" if block.get("is_error") else "ok"
                transcript += [f"**tool_result** ({mark}, for `{block.get('tool_use_id')}`)", "",
                               "```", result_text(block), "```", ""]
                continue

            text = block.get("text") or ""
            if etype == "user":
                if not side and not is_noise_user(entry, text):
                    index += ["", f"### `{anchor}` USER", "", clip(text, PROMPT_CHARS), ""]
                transcript += [text, ""]
            elif etype == "assistant":
                if not side and text.strip():
                    index += ["", f"`{anchor}` **assistant:** " + clip(text, PROSE_CHARS), ""]
                transcript += [text, ""]
            else:
                transcript += [text, ""]

    index += ["", "---", "", f"_End of INDEX. Detail: `{stamp}--checkpoint--TRANSCRIPT.md` (grep it)._", ""]
    transcript += ["", "---", "", "_End of TRANSCRIPT._", ""]
    return "\n".join(index), "\n".join(transcript)


def unique_stamp(out_dir: Path) -> str:
    base = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    stamp, n = base, 1
    while (out_dir / f"{stamp}--checkpoint--INDEX.md").exists():
        n += 1
        stamp = f"{base}-{n}"
    return stamp


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a session .jsonl into a checkpoint pair.")
    ap.add_argument("--session-file", help="transcript .jsonl (default: newest for --cwd)")
    ap.add_argument("--cwd", default=os.getcwd(), help="project dir the session ran in")
    ap.add_argument("--out-dir", help="default: <cwd>/.session-state/checkpoints")
    ap.add_argument("--projects-root", default=str(Path.home() / ".claude" / "projects"))
    args = ap.parse_args(argv)

    session_file = (
        Path(args.session_file).expanduser()
        if args.session_file
        else find_session_file(args.cwd, Path(args.projects_root).expanduser())
    )
    if not session_file.is_file():
        raise SystemExit(f"not a file: {session_file}")

    entries = load(session_file)
    if not entries:
        raise SystemExit(f"no usable entries in {session_file}")

    header = gather_header(entries, session_file, args.cwd)
    # Anchored on the invocation cwd, not the transcript's: a checkpoint lands in
    # the checkout you are standing in, never in someone else's worktree.
    out_dir = Path(args.out_dir) if args.out_dir else Path(args.cwd) / ".session-state" / "checkpoints"
    out_dir.mkdir(parents=True, exist_ok=True)

    stamp = unique_stamp(out_dir)
    index_md, transcript_md = render(entries, header, stamp)
    index_path = out_dir / f"{stamp}--checkpoint--INDEX.md"
    transcript_path = out_dir / f"{stamp}--checkpoint--TRANSCRIPT.md"
    index_path.write_text(index_md, encoding="utf-8")
    transcript_path.write_text(transcript_md, encoding="utf-8")

    print(f"INDEX      {index_path}  ({index_path.stat().st_size / 1024:.1f} KB)")
    print(f"TRANSCRIPT {transcript_path}  ({transcript_path.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
