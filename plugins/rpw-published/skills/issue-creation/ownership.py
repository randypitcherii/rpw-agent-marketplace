"""Deterministic repo-ownership classification for the issue-creation skill.

The skill's whole policy fork hangs off one question: *is this repo one the
operator owns, or someone else's?* Owned repos get the canonical house issue
structure; external repos defer to whatever standards that repo documents.
Answering it by vibes produces the exact failure the skill exists to prevent —
house style imposed on an external maintainer's tracker.

So the answer is computed here, from two facts and one config value:

    repo owner login   `gh repo view <repo> --json owner -q .owner.login`
    viewer login       `gh api user -q .login`
    owned orgs         RPW_OWNED_ORGS env var (comma-separated), or explicit arg

Two rules that are easy to get wrong and are therefore pinned by tests:

* **Write/admin permission does NOT imply ownership.** Being a maintainer on
  someone else's project is exactly the case where their conventions govern.
  `viewerPermission` is deliberately never consulted.
* **Unknown resolves to EXTERNAL.** If either login is missing or unreadable
  the classifier fails toward deference, because the cost of over-deferring is
  a slightly plainer issue on your own repo, while the cost of under-deferring
  is ignoring a stranger's CONTRIBUTING.md.

Membership in an org is not ownership either, so orgs must be named explicitly
via `RPW_OWNED_ORGS`; the classifier never expands `gh api user/orgs` for you.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Iterable, NamedTuple

OWNED = "OWNED"
EXTERNAL = "EXTERNAL"

#: Env var naming additional orgs whose repos count as owned (comma-separated).
OWNED_ORGS_ENV = "RPW_OWNED_ORGS"

REASON_VIEWER_IS_OWNER = "repo owner is the authenticated user"
REASON_OWNED_ORG = "repo owner is a configured owned org"
REASON_NOT_OWNED = "repo owner is neither the authenticated user nor an owned org"
REASON_UNKNOWN_OWNER = "repo owner could not be determined"
REASON_UNKNOWN_VIEWER = "authenticated user could not be determined"


class OwnershipResult(NamedTuple):
    """Classification plus the reason, so callers can explain the fork."""

    classification: str
    owner: str
    viewer: str
    reason: str

    @property
    def is_owned(self) -> bool:
        return self.classification == OWNED


def _normalize(login: object) -> str:
    """Lowercase + strip a login. Non-strings and blanks normalize to ""."""
    if not isinstance(login, str):
        return ""
    return login.strip().lower()


def parse_owned_orgs(raw: object) -> tuple[str, ...]:
    """Parse a comma-separated owned-org list into normalized, deduped logins.

    Accepts the raw env-var string (or None). Blank entries and duplicates are
    dropped; order of first appearance is preserved so error messages read the
    way the operator wrote them.
    """
    if not isinstance(raw, str):
        return ()
    seen: list[str] = []
    for chunk in raw.split(","):
        login = _normalize(chunk)
        if login and login not in seen:
            seen.append(login)
    return tuple(seen)


def owned_orgs_from_env(environ: object = None) -> tuple[str, ...]:
    """Read the owned-org list from the environment (defaults to os.environ)."""
    env = os.environ if environ is None else environ
    return parse_owned_orgs(env.get(OWNED_ORGS_ENV))


def classify(
    repo_owner: object,
    viewer_login: object,
    owned_orgs: Iterable[str] = (),
) -> OwnershipResult:
    """Classify a repo as OWNED or EXTERNAL from its owner and the viewer login.

    Comparison is case-insensitive (GitHub logins are case-preserving but
    case-insensitive). Anything unknown resolves to EXTERNAL.
    """
    owner = _normalize(repo_owner)
    viewer = _normalize(viewer_login)
    orgs = {_normalize(o) for o in owned_orgs} - {""}

    if not owner:
        return OwnershipResult(EXTERNAL, owner, viewer, REASON_UNKNOWN_OWNER)
    if not viewer:
        # An owned-org match still needs no viewer identity, so check it first.
        if owner in orgs:
            return OwnershipResult(OWNED, owner, viewer, REASON_OWNED_ORG)
        return OwnershipResult(EXTERNAL, owner, viewer, REASON_UNKNOWN_VIEWER)
    if owner == viewer:
        return OwnershipResult(OWNED, owner, viewer, REASON_VIEWER_IS_OWNER)
    if owner in orgs:
        return OwnershipResult(OWNED, owner, viewer, REASON_OWNED_ORG)
    return OwnershipResult(EXTERNAL, owner, viewer, REASON_NOT_OWNED)


def classify_gh_payload(
    repo_json: object,
    viewer_json: object,
    owned_orgs: Iterable[str] = (),
) -> OwnershipResult:
    """Classify from raw `gh repo view --json owner` + `gh api user` payloads.

    `viewerPermission` is present in some repo payloads and is intentionally
    ignored: ADMIN on a repo you do not own is still an external repo.
    """
    repo = repo_json if isinstance(repo_json, dict) else {}
    viewer = viewer_json if isinstance(viewer_json, dict) else {}
    owner_block = repo.get("owner")
    owner_login = owner_block.get("login") if isinstance(owner_block, dict) else None
    return classify(owner_login, viewer.get("login"), owned_orgs)


def _gh_json(args: list[str]) -> object:
    """Run a `gh` command and parse its JSON stdout; return None on any failure."""
    try:
        out = subprocess.run(
            ["gh", *args], capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI: print the classification for a repo as JSON.

    `uv run --no-project python ownership.py` classifies the current directory's
    repo; add `--repo owner/name` to classify a named one. Python goes through
    `uv`, and `--no-project` keeps the target repo's own environment out of it —
    this is stdlib-only and must answer even where that project cannot resolve.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", help="owner/name (default: repo in cwd)")
    parser.add_argument(
        "--owned-orgs",
        help=f"comma-separated owned orgs (default: ${OWNED_ORGS_ENV})",
    )
    ns = parser.parse_args(argv)

    repo_args = ["repo", "view", "--json", "owner,nameWithOwner"]
    if ns.repo:
        if not re.fullmatch(r"[\w.-]+/[\w.-]+", ns.repo):
            print(f"invalid --repo (want owner/name): {ns.repo}", file=sys.stderr)
            return 2
        repo_args.insert(2, ns.repo)
    orgs = (
        parse_owned_orgs(ns.owned_orgs)
        if ns.owned_orgs is not None
        else owned_orgs_from_env()
    )
    result = classify_gh_payload(
        _gh_json(repo_args), _gh_json(["api", "user"]), orgs
    )
    print(json.dumps(result._asdict(), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    sys.exit(main())
