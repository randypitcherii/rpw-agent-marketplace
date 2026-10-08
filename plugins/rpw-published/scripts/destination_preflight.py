#!/usr/bin/env python3
"""Is this the destination the human named? — asked before `gh pr create` (#797).

A wave worker was briefed against a repo its supervisor believed the user owned.
It was a fork, 973 commits behind upstream, so half the target code did not
exist. The worker's engineering call — rebase onto the upstream — was right. Its
next call, **redirecting the PR to the public upstream**, was not its call to
make, and nothing in the brief said so. A public, non-draft PR landed in the
user's name, +600/-56 across 16 files, with no user message anywhere in the
transcript naming that destination.

The disclosure review found the concrete harm low. That is exactly why the fix
belongs on the **consent** axis rather than the content axis: the secret scan and
the sensitive-content check already own *what* leaves, and they had nothing to
say about *where* it went. The next instance may not be as harmless.

So this resolves the destination before anything is created, and refuses three
classes of target:

    refused        owner outside the allowlist, or visibility is PUBLIC
    blocked-drift  a fork, a base branch that does not exist — "the repo the
                   human named" and "the repo the code must land in" differ, and
                   reconciling them is not a worker's decision
    unprovable     `gh` could not be asked at all

**The third one is the whole design.** "GitHub says this repo is private" and
"GitHub was never asked" must not be the same value, because a preflight that
fails open manufactures confidence — it is worse than no preflight, since a
worker reasonably treats a pass as consent. This wave's counterbalance review
found that exact conflation three times in ``automation/bin/wave-liveness.py``;
PR #1910 fixed it with a tri-state in ``Gh._json``, and this follows that shape
rather than inventing a second one. Every failed read lands on ``unprovable``,
and ``unprovable`` exits nonzero.

What this deliberately does NOT do:

* **It does not prohibit.** The ask is consent. A human sets
  ``RPW_DESTINATION_OPT_IN`` (or passes ``--opt-in``) naming the exact
  ``owner/repo``, and the target is allowed. There are no wildcards: consent to
  one destination is not consent to the next one. An *agent* setting that
  variable has re-created the incident, which is why the brief template says so
  in as many words.
* **It does not touch routine delivery.** A private repo in the allowlist passes
  silently, on any base branch, because the user's standing preference is that
  feature delivery into their own repos and integration branch is fully
  autonomous (root ``AGENTS.md``, #1878). This gate must not regress that, so a
  named base that is merely not the default branch is a *note*, never a verdict
  — wave branches are not the default branch and never will be.
* **It does not scan content.** ``scripts/public_release_gate.py`` and the secret
  scan own that axis. It composes with the ``PUBLIC_REPO_RELEASE_CONFIRM`` gate,
  which covers the mirror path but not arbitrary third-party repos.

Stdlib only, so it runs from a worker sandbox with no venv built.

Usage::

    uv run python plugins/rpw-published/scripts/destination_preflight.py \\
        owner/repo --base main

    RPW_DESTINATION_ALLOWLIST=octocat \\
    RPW_DESTINATION_OPT_IN=upstream/project \\
        ... destination_preflight.py upstream/project

Read the LAST stdout line (``outcome=<verdict>``), not the exit code: a caller
that reads only ``$?`` cannot tell ``refused`` from ``unprovable``, and those
two owe a worker different reports.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Callable, Optional, Sequence

#: Outcome of one read. Tri-state on purpose, the same shape (and for the same
#: reason) as ``automation/bin/wave-liveness.py``: an answer and the absence of
#: one are different values. ``empty`` counts as a failure deliberately — an
#: exit-0 ``gh --json`` that prints nothing is not the answer "no", it is no
#: answer at all.
READ_OK = "ok"
READ_EMPTY = "empty"
READ_UNREACHABLE = "unreachable"

#: Verdict -> exit code. Fails CLOSED: only `allowed` is dispatchable, and the
#: three refusals are distinct so a worker can report which one it hit.
ALLOWED = "allowed"
REFUSED = "refused"
BLOCKED_DRIFT = "blocked-drift"
UNPROVABLE = "unprovable"

EXIT_CODES = {
    ALLOWED: 0,
    REFUSED: 3,
    BLOCKED_DRIFT: 4,
    UNPROVABLE: 5,
}

#: Severity, worst first. A target can trip several findings at once (a public
#: fork trips two); every finding is printed, and the verdict is the worst of
#: them. `unprovable` outranks the rest: if a read failed, the facts underneath
#: any other verdict are incomplete, and claiming a specific verdict on partial
#: reads is the fail-open behaviour this module exists to prevent.
SEVERITY = (UNPROVABLE, REFUSED, BLOCKED_DRIFT, ALLOWED)

ALLOWLIST_ENV = "RPW_DESTINATION_ALLOWLIST"
OPT_IN_ENV = "RPW_DESTINATION_OPT_IN"

#: GitHub's own limits: owner and repo names are ASCII word characters plus
#: `-`, `.` and `_`. Strict, and no URL forms — normalizing
#: `https://host/owner/repo` would let the host segment smuggle an owner name
#: past the allowlist check, and the allowlist check is the entire point.
_TARGET_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)/([A-Za-z0-9][A-Za-z0-9._-]*)$")

#: `git remote get-url origin` forms, used only to learn the local namespace.
_REMOTE_RES = (
    re.compile(r"^(?:https?|ssh)://[^/]+/([^/]+)/([^/]+?)(?:\.git)?/?$"),
    re.compile(r"^[^@]+@[^:]+:([^/]+)/([^/]+?)(?:\.git)?/?$"),
)

#: (argv) -> CompletedProcess. Injected so tests never shell out to the network.
Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess"]


def default_runner(cmd: Sequence[str]) -> "subprocess.CompletedProcess":
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=60)


def _complain(what: str, detail: str) -> None:
    """One line to stderr. A refusal whose cause is invisible gets overridden."""
    first = (detail or "").strip().splitlines()
    print(
        "destination-preflight: %s failed: %s" % (what, first[0] if first else "no detail"),
        file=sys.stderr,
    )


# --- pure helpers -------------------------------------------------------------


def parse_target(value: str) -> "Optional[tuple[str, str]]":
    """`owner/repo` -> (owner, repo), or None. Rejects URLs and bare names."""
    m = _TARGET_RE.match((value or "").strip())
    return (m.group(1), m.group(2)) if m else None


def split_list(value: Optional[str]) -> "list[str]":
    """Comma- or whitespace-separated list, empties dropped."""
    if not value:
        return []
    return [part for part in re.split(r"[,\s]+", value.strip()) if part]


def owner_from_remote_url(url: str) -> Optional[str]:
    for pattern in _REMOTE_RES:
        m = pattern.match((url or "").strip())
        if m:
            return m.group(1)
    return None


def local_owner(run: Runner, cwd: Optional[str] = None) -> Optional[str]:
    """The namespace of `origin`, as the allowlist's default.

    Local and offline on purpose: the fallback for "nobody told me whose repos
    are trusted" must not itself depend on the API whose absence is the thing
    being guarded against. If this fails too, the caller has no allowlist and
    refuses as `unprovable` rather than guessing one.
    """
    argv = ["git", "remote", "get-url", "origin"]
    if cwd:
        argv = ["git", "-C", cwd, "remote", "get-url", "origin"]
    try:
        proc = run(argv)
    except Exception as exc:  # git missing, timeout, OSError
        _complain("git remote get-url origin", "%s: %s" % (type(exc).__name__, exc))
        return None
    if proc.returncode != 0:
        _complain(
            "git remote get-url origin",
            "exit %s: %s" % (proc.returncode, proc.stderr or ""),
        )
        return None
    return owner_from_remote_url(proc.stdout or "")


def worst(verdicts: Sequence[str]) -> str:
    for candidate in SEVERITY:
        if candidate in verdicts:
            return candidate
    return ALLOWED


# --- the reads ----------------------------------------------------------------


class Gh:
    """The three reads this needs, each reporting WHETHER it succeeded.

    No call raises and no call claims an empty answer. Degrading is fine;
    *lying* is what turns a preflight into a rubber stamp.
    """

    def __init__(self, runner: Runner = default_runner):
        self._run = runner

    def _json(self, cmd: Sequence[str], label: str) -> "tuple[str, object]":
        """(read_status, parsed). Never raises, never invents an answer."""
        try:
            proc = self._run(list(cmd))
        except Exception as exc:  # gh missing, timeout, OSError
            _complain(label, "%s: %s" % (type(exc).__name__, exc))
            return READ_UNREACHABLE, None
        if proc.returncode != 0:
            _complain(label, "exit %s: %s" % (proc.returncode, proc.stderr or ""))
            return READ_UNREACHABLE, None
        if not (proc.stdout or "").strip():
            _complain(label, "exit 0 but printed nothing")
            return READ_EMPTY, None
        try:
            return READ_OK, json.loads(proc.stdout)
        except (ValueError, TypeError):
            _complain(label, "exit 0 but the output is not JSON")
            return READ_UNREACHABLE, None

    def repo(self, target: str) -> "tuple[str, Optional[dict]]":
        """The one read the issue names: owner, visibility, isFork, parent."""
        status, payload = self._json(
            [
                "gh", "repo", "view", target, "--json",
                "nameWithOwner,owner,visibility,isFork,parent,defaultBranchRef",
            ],
            "gh repo view %s" % target,
        )
        if status != READ_OK:
            return status, None
        if not isinstance(payload, dict) or "visibility" not in payload:
            _complain("gh repo view %s" % target, "JSON without the fields asked for")
            return READ_UNREACHABLE, None
        return READ_OK, payload

    def behind_by(
        self, parent: str, parent_base: str, fork_owner: str, fork_base: str
    ) -> "tuple[str, Optional[int]]":
        """How far the fork's base trails the parent's — the 973 in the incident."""
        ref = "%s...%s:%s" % (parent_base, fork_owner, fork_base)
        status, payload = self._json(
            ["gh", "api", "repos/%s/compare/%s" % (parent, ref)],
            "gh api compare %s/%s" % (parent, ref),
        )
        if status != READ_OK:
            return status, None
        if not isinstance(payload, dict) or not isinstance(payload.get("behind_by"), int):
            _complain("gh api compare %s/%s" % (parent, ref), "no behind_by in the JSON")
            return READ_UNREACHABLE, None
        return READ_OK, int(payload["behind_by"])

    def branch_exists(self, target: str, base: str) -> "tuple[str, Optional[bool]]":
        """Does `base` exist on `target`?

        `git/matching-refs` and not `branches/<base>`, for the tri-state: a
        missing branch is exit 0 with `[]`, so "no such branch" stays
        distinguishable from "the API could not be asked", which `branches/…`
        reports as the same nonzero exit. The endpoint matches by PREFIX, so the
        exact ref has to be found in the list rather than the list merely being
        non-empty (`heads/produc` returns `refs/heads/production`).
        """
        path = "repos/%s/git/matching-refs/heads/%s" % (target, base)
        status, payload = self._json(["gh", "api", path], "gh api %s" % path)
        if status == READ_EMPTY:
            # `gh api` prints `[]` for no match, so silence is not "no match".
            return READ_EMPTY, None
        if status != READ_OK:
            return status, None
        if not isinstance(payload, list):
            _complain("gh api %s" % path, "expected a JSON array of refs")
            return READ_UNREACHABLE, None
        wanted = "refs/heads/%s" % base
        return READ_OK, any(
            isinstance(row, dict) and row.get("ref") == wanted for row in payload
        )


# --- resolution ---------------------------------------------------------------


class Result:
    """Verdict + the findings behind it + the facts a human needs to judge it."""

    def __init__(self) -> None:
        self.findings: "list[tuple[str, str, str]]" = []  # (verdict, code, detail)
        self.facts: "list[tuple[str, str]]" = []

    def find(self, verdict: str, code: str, detail: str) -> None:
        self.findings.append((verdict, code, detail))

    def fact(self, key: str, value: object) -> None:
        self.facts.append((key, str(value)))

    @property
    def verdict(self) -> str:
        return worst([v for v, _, _ in self.findings])

    @property
    def exit_code(self) -> int:
        return EXIT_CODES[self.verdict]


def resolve(
    target: str,
    *,
    gh: Gh,
    allowlist: Sequence[str],
    opt_in: Sequence[str],
    base: Optional[str] = None,
) -> Result:
    """Every check runs; the worst finding is the verdict.

    Checks are not short-circuited: a public fork is both out-of-policy and
    drifted, and a human resolving it needs to see both. Only a target that
    cannot be parsed stops the walk, since there is nothing left to ask about.
    """
    out = Result()
    out.fact("target", target)
    if base:
        out.fact("requested_base", base)

    parsed = parse_target(target)
    if not parsed:
        out.find(
            REFUSED,
            "target-unparseable",
            "%r is not `owner/repo`. Pass the destination as `owner/repo` — a URL "
            "is refused on purpose, because its host segment can smuggle an owner "
            "name past the allowlist." % target,
        )
        return out
    owner, _repo = parsed
    out.fact("owner", owner)

    opted_in = target in set(opt_in)
    out.fact("opted_in", "yes" if opted_in else "no")

    if not allowlist:
        out.find(
            UNPROVABLE,
            "allowlist-unknown",
            "no trusted namespace: %s is unset, --allow-owner was not passed, and "
            "`git remote get-url origin` could not be read. Nothing here can judge "
            "a destination without knowing whose repos are the user's."
            % ALLOWLIST_ENV,
        )
        return out
    out.fact("allowlist", ",".join(allowlist))

    status, repo = gh.repo(target)
    if status != READ_OK or repo is None:
        out.find(
            UNPROVABLE,
            "repo-read-%s" % status,
            "`gh repo view %s` did not answer (%s). This REFUSES: a read that "
            "failed is not the answer 'private'. Fix `gh` (auth, network) and "
            "re-run, or escalate — do not proceed on this." % (target, status),
        )
        return out

    visibility = str(repo.get("visibility") or "UNKNOWN").upper()
    is_fork = bool(repo.get("isFork"))
    parent = repo.get("parent") or None
    default_branch = ((repo.get("defaultBranchRef") or {}) or {}).get("name")
    out.fact("visibility", visibility)
    out.fact("is_fork", "yes" if is_fork else "no")
    out.fact("default_branch", default_branch or "unknown")

    # --- consent axis ---------------------------------------------------------
    if owner not in set(allowlist):
        out.find(
            ALLOWED if opted_in else REFUSED,
            "owner-outside-allowlist",
            "owner `%s` is not in the allowlist (%s)."
            % (owner, ",".join(allowlist)),
        )
    if visibility != "PRIVATE":
        out.find(
            ALLOWED if opted_in else REFUSED,
            "visibility-%s" % visibility.lower(),
            "the base repo is %s, so anything created here is published the "
            "moment it exists — regardless of who owns it." % visibility,
        )

    # --- drift axis -----------------------------------------------------------
    if is_fork:
        parent_name = _parent_name(parent)
        out.fact("parent", parent_name or "unknown")
        behind = None
        if parent_name and default_branch:
            pstatus, prepo = gh.repo(parent_name)
            if pstatus != READ_OK or prepo is None:
                out.find(
                    UNPROVABLE,
                    "parent-read-%s" % pstatus,
                    "`%s` is a fork of `%s`, and the parent could not be read "
                    "(%s) — so how far this base trails upstream is unknown. "
                    "Unknown drift REFUSES." % (target, parent_name, pstatus),
                )
            else:
                parent_base = (
                    ((prepo.get("defaultBranchRef") or {}) or {}).get("name")
                    or default_branch
                )
                bstatus, behind = gh.behind_by(
                    parent_name, parent_base, owner, base or default_branch
                )
                if bstatus != READ_OK or behind is None:
                    out.find(
                        UNPROVABLE,
                        "compare-read-%s" % bstatus,
                        "could not compare `%s` against `%s` (%s), so commits-behind "
                        "is unknown. Unknown drift REFUSES."
                        % (target, parent_name, bstatus),
                    )
                else:
                    out.fact("behind_by", behind)
        out.find(
            ALLOWED if opted_in else BLOCKED_DRIFT,
            "destination-is-a-fork",
            "`%s` is a fork of `%s`%s. 'The repo the human named' and 'the repo "
            "the code must land in' may not be the same repo — report `isFork`, "
            "`parent` and commits-behind to whoever wrote your brief and let "
            "THEM pick. Rebasing onto the parent is a fine engineering call; "
            "retargeting the PR to it is not yours to make."
            % (
                target,
                parent_name or "an unreadable parent",
                "" if behind is None else ", %d commits behind its base" % behind,
            ),
        )

    if base:
        bstatus, exists = gh.branch_exists(target, base)
        if bstatus != READ_OK or exists is None:
            out.find(
                UNPROVABLE,
                "base-read-%s" % bstatus,
                "could not check whether `%s` exists on `%s` (%s). Unknown base "
                "REFUSES." % (base, target, bstatus),
            )
        elif not exists:
            out.find(
                ALLOWED if opted_in else BLOCKED_DRIFT,
                "base-missing",
                "`%s` has no branch `%s` (its default is `%s`). A renamed default "
                "branch or a moved upstream is a conflict to STATE, not to "
                "resolve alone." % (target, base, default_branch or "unknown"),
            )
        elif default_branch and base != default_branch:
            # A NOTE, never a verdict: wave branches are not default branches,
            # and refusing here would break the autonomous delivery this gate is
            # required not to regress (#1878).
            out.fact("base_is_not_default", "yes")

    if not out.findings:
        out.find(ALLOWED, "in-namespace-private", "in the allowlist, private, no drift.")
    return out


def _parent_name(parent: Optional[dict]) -> Optional[str]:
    """`parent` from `gh repo view` carries `{name, owner:{login}}`, not a slug."""
    if not isinstance(parent, dict):
        return None
    name = parent.get("nameWithOwner")
    if isinstance(name, str) and "/" in name:
        return name
    login = ((parent.get("owner") or {}) or {}).get("login")
    repo = parent.get("name")
    if login and repo:
        return "%s/%s" % (login, repo)
    return None


# --- reporting ----------------------------------------------------------------


def render(result: Result) -> str:
    lines = ["destination-preflight:"]
    for key, value in result.facts:
        lines.append("  %-18s %s" % (key, value))
    if result.findings:
        lines.append("findings:")
    for verdict, code, detail in result.findings:
        lines.append("  [%s] %s: %s" % (verdict, code, detail))
    lines.append(_ADVICE.get(result.verdict, ""))
    # Last line, machine-readable, and the one a caller must read: the exit code
    # alone cannot tell `refused` from `unprovable`.
    lines.append("outcome=%s" % result.verdict)
    return "\n".join(line for line in lines if line != "")


_ADVICE = {
    ALLOWED: "proceed: this destination is the one you were given.",
    REFUSED: (
        "STOP and report this as a blocker. Do NOT set %s yourself — consent is "
        "the human's to give, and an agent opting itself in is the incident this "
        "gate exists for (#797)." % OPT_IN_ENV
    ),
    BLOCKED_DRIFT: (
        "STOP and report the drift above to whoever wrote your brief, BEFORE any "
        "push. Naming the conflict is the deliverable; resolving it is not."
    ),
    UNPROVABLE: (
        "STOP: this is not a pass. Nothing above was established, so treat it as "
        "a refusal and report WHICH read could not be made (the finding names it)."
    ),
}


# --- cli ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve an outward-facing destination before creating anything there "
            "(#797). Refuses out-of-namespace, public, drifted and unprovable "
            "targets; exits 0 only on `allowed`."
        ),
    )
    parser.add_argument("target", help="destination repo as `owner/repo`")
    parser.add_argument(
        "--base",
        default=None,
        help="base branch the brief named; checked for existence, and reported "
        "when it is not the default branch (a note, never a refusal)",
    )
    parser.add_argument(
        "--allow-owner",
        action="append",
        default=[],
        help="trusted owner; repeatable or comma-separated. Defaults to %s, then "
        "the owner of `origin`." % ALLOWLIST_ENV,
    )
    parser.add_argument(
        "--opt-in",
        action="append",
        default=[],
        help="exact `owner/repo` a HUMAN has consented to. Repeatable or "
        "comma-separated; no wildcards. Also read from %s." % OPT_IN_ENV,
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="directory whose `origin` supplies the default allowlist "
        "(default: the current directory)",
    )
    return parser


def resolve_allowlist(
    flags: Sequence[str],
    *,
    env: "dict[str, str]",
    run: Runner,
    repo_root: Optional[str] = None,
) -> "list[str]":
    """Flags, then the environment, then `origin`'s owner. First non-empty wins."""
    from_flags: "list[str]" = []
    for value in flags:
        from_flags.extend(split_list(value))
    if from_flags:
        return from_flags
    from_env = split_list(env.get(ALLOWLIST_ENV))
    if from_env:
        return from_env
    owner = local_owner(run, repo_root)
    return [owner] if owner else []


def resolve_opt_in(flags: Sequence[str], *, env: "dict[str, str]") -> "list[str]":
    """Flags AND the environment: a human may have recorded consent in either."""
    values: "list[str]" = []
    for value in flags:
        values.extend(split_list(value))
    values.extend(split_list(env.get(OPT_IN_ENV)))
    return values


def main(argv: Optional[Sequence[str]] = None, *, runner: Runner = default_runner) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    env = dict(os.environ)
    result = resolve(
        args.target,
        gh=Gh(runner),
        allowlist=resolve_allowlist(
            args.allow_owner, env=env, run=runner, repo_root=args.repo_root
        ),
        opt_in=resolve_opt_in(args.opt_in, env=env),
        base=args.base,
    )
    print(render(result))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
