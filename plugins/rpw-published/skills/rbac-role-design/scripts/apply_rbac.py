#!/usr/bin/env python3
"""Declarative OAR/BFR role map for Unity Catalog — copy, edit ROLE MAP, run.

The whole access model lives in the ROLE MAP section below: account groups
(object access roles + business function roles), the membership graph, and
every UC grant they imply. Catalogs and grants are deliberately NOT Databricks
Asset Bundle resources (see the rbac-role-design skill, references/dabs-boundary.md).

Idempotent — safe to re-run. Dry run by default; each mutation class has its
own gate, so the human approves a printed plan and the apply is exactly that plan:

    uv run --no-project python apply_rbac.py --offline     # plan vs empty state, no auth
    uv run --no-project python apply_rbac.py               # dry run vs live state
    uv run --no-project python apply_rbac.py --apply       # groups + memberships + grants
    uv run --no-project python apply_rbac.py --apply --transfer-ownership
    uv run --no-project python apply_rbac.py --verify      # read-only: SHOW GRANTS + effective perms

Auth: the `databricks` CLI with an ACCOUNT profile (groups/SCIM) and a
WORKSPACE profile + SQL warehouse (grants). Pass them as flags or env vars
RBAC_ACCOUNT_PROFILE / RBAC_WORKSPACE_PROFILE / RBAC_WAREHOUSE_ID.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field

# =============================================================== ROLE MAP ==
# Replace the example below with your deployment. Everything else is plumbing.

# Securable scopes: scope name -> (securable type, full name). Scope at
# CATALOG level by default; SCHEMA only when one schema's audience differs.
# Never table — UC inheritance makes one catalog grant cover every child.
SCOPES: dict[str, tuple[str, str]] = {
    "sales_prod": ("CATALOG", "sales_prod"),
    "sales_dev": ("CATALOG", "sales_dev"),
}

# OARs (object access roles): scope -> tiers. Each tier mints the account group
# `<scope>_<tier>`. OARs are the ONLY grantees of privileges and never hold a
# human or service principal directly — only BFR groups, as members.
OARS: dict[str, list[str]] = {
    "sales_prod": ["read", "write", "owner"],
    "sales_dev": ["write", "owner"],
}

# BFRs (business function roles): named for jobs. The ONLY groups people and
# service principals join. `member_of` lists the OARs this BFR is nested INTO
# — the BFR group becomes a MEMBER of each OAR group (the REVERSE of
# Snowflake's `GRANT ROLE oar TO ROLE bfr`). `users: None` = leave unmanaged.
BFRS: dict[str, dict] = {
    "sales_admin": {
        "users": ["admin@example.com"],
        "service_principals": [],
        "member_of": ["sales_prod_owner", "sales_dev_owner"],
    },
    "sales_engineer": {
        "users": ["engineer@example.com"],
        "service_principals": [],
        "member_of": ["sales_dev_write", "sales_prod_read"],
    },
    "sales_analyst": {
        "users": ["analyst@example.com"],
        "service_principals": [],
        "member_of": ["sales_prod_read"],
    },
    "sales_pipeline": {
        "users": [],
        "service_principals": ["sales-pipeline-sp"],  # application id, or a UNIQUE display name
        "member_of": ["sales_prod_write"],
    },
}
# ================================================================ /ROLE MAP ==

TIERS = ("read", "write", "owner")
SECURABLE_TYPES = ("CATALOG", "SCHEMA")
# What the effective-permissions API must show for a principal in each tier.
EXPECTED_PRIVILEGES = {"read": {"SELECT"}, "write": {"ALL_PRIVILEGES"}}


def q(name: str) -> str:
    """Backtick-quote a (possibly dotted) identifier."""
    return ".".join(f"`{part}`" for part in name.split("."))


def oar_name(scope: str, tier: str) -> str:
    return f"{scope}_{tier}"


def role_map() -> dict:
    return {"scopes": SCOPES, "oars": OARS, "bfrs": BFRS}


def oar_names(rm: dict) -> list[str]:
    return [oar_name(s, t) for s, tiers in rm["oars"].items() for t in tiers]


# ---------------------------------------------------------- validation --
def validate_role_map(rm: dict) -> list[str]:
    """Structural errors that would make the pattern lie. Empty list = valid."""
    errors: list[str] = []
    scopes, oars, bfrs = rm["scopes"], rm["oars"], rm["bfrs"]
    for scope, (kind, full) in scopes.items():
        if kind not in SECURABLE_TYPES:
            errors.append(f"scope {scope}: type {kind!r} not in {SECURABLE_TYPES} (never table-level)")
        elif kind == "CATALOG" and "." in full:
            errors.append(f"scope {scope}: CATALOG name {full!r} must not be dotted")
        elif kind == "SCHEMA" and full.count(".") != 1:
            errors.append(f"scope {scope}: SCHEMA name {full!r} must be <catalog>.<schema>")
    for scope, tiers in oars.items():
        if scope not in scopes:
            errors.append(f"OAR scope {scope!r} is not declared in SCOPES")
        for tier in tiers:
            if tier not in TIERS:
                errors.append(f"OAR {scope}: tier {tier!r} not in {TIERS}")
    valid_oars = set(oar_names(rm))
    for bfr, spec in bfrs.items():
        if bfr in valid_oars or bfr.endswith(tuple(f"_{t}" for t in TIERS)):
            errors.append(f"BFR {bfr!r} is named like an OAR — name BFRs for jobs")
        for target in spec.get("member_of", []):
            if target in bfrs:
                errors.append(
                    f"BFR {bfr} member_of {target!r}, which is a BFR — member_of must name "
                    "OARs only (BFRs compose access purely from OARs)"
                )
            elif target not in valid_oars:
                errors.append(f"BFR {bfr} member_of {target!r}, which is not a declared OAR")
    return errors


# ----------------------------------------------------------- planning --
@dataclass
class State:
    """Live account state, keyed by name. Member sets hold SCIM member ids."""

    users: dict[str, str] = field(default_factory=dict)  # userName -> id
    sps: dict[str, str] = field(default_factory=dict)  # displayName/applicationId -> id
    # A name that maps to more than one SP id: never resolved, refused like MISSING.
    ambiguous_sps: dict[str, list[str]] = field(default_factory=dict)  # name -> ids
    groups: dict[str, str] = field(default_factory=dict)  # displayName -> id
    members: dict[str, set[str]] = field(default_factory=dict)  # group name -> member ids


@dataclass(frozen=True)
class Action:
    kind: str  # create_group | add_member | grant | ownership
    target: str  # group name, or securable full name for grant/ownership
    member: tuple[str, str] | None = None  # ("user"|"sp"|"group", name)
    sql: str | None = None

    def describe(self) -> str:
        if self.kind == "create_group":
            return f"create group   {self.target}"
        if self.kind == "add_member":
            return f"add member     {self.member[0]}:{self.member[1]} -> {self.target}"
        return f"{self.kind:<14} {self.sql}"


def index_service_principals(sps: list[dict]) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Map displayName and applicationId to SP id, splitting out ambiguous names.

    Display names are not unique in an account. A name that matches more than one SP
    is returned in the second dict and never resolved, so the plan cannot add the
    wrong principal (#1312). applicationId is unique and always resolves.
    """
    ids_by_key: dict[str, set[str]] = {}
    for sp in sps:
        for key in (sp.get("displayName", ""), sp.get("applicationId", "")):
            if key:
                ids_by_key.setdefault(key, set()).add(str(sp["id"]))
    unique = {k: next(iter(v)) for k, v in ids_by_key.items() if len(v) == 1}
    ambiguous = {k: sorted(v) for k, v in ids_by_key.items() if len(v) > 1}
    return unique, ambiguous


def grant_statements(rm: dict, scope: str, tier: str) -> list[str]:
    kind, full = rm["scopes"][scope]
    grantee = q(oar_name(scope, tier))
    if tier == "owner":
        return []  # owner OARs receive OWNERSHIP, not grants (gated separately)
    if kind == "CATALOG":
        privs = "USE CATALOG, USE SCHEMA, SELECT" if tier == "read" else "ALL PRIVILEGES"
        return [f"GRANT {privs} ON CATALOG {q(full)} TO {grantee}"]
    catalog = full.split(".")[0]
    privs = "USE SCHEMA, SELECT" if tier == "read" else "ALL PRIVILEGES"
    return [
        f"GRANT USE CATALOG ON CATALOG {q(catalog)} TO {grantee}",
        f"GRANT {privs} ON SCHEMA {q(full)} TO {grantee}",
    ]


def build_plan(rm: dict, state: State) -> tuple[list[Action], list[str], list[str]]:
    """Diff the role map against live state.

    Returns (actions, missing principals, ambiguous principals). The two refusal kinds
    are separate lists, never one list told apart by its message text (#1312).
    """
    actions: list[Action] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    oars, bfrs = oar_names(rm), rm["bfrs"]

    def needs(group: str, member_id: str | None) -> bool:
        if group not in state.groups or member_id is None:
            return True
        return member_id not in state.members.get(group, set())

    # 1. every group exists
    for name in oars + list(bfrs):
        if name not in state.groups:
            actions.append(Action("create_group", name))
    # 2. principals into BFRs (never into OARs)
    for bfr, spec in bfrs.items():
        if spec.get("users") is not None:
            for user in spec["users"]:
                if user not in state.users:
                    missing.append(f"user {user} (BFR {bfr})")
                elif needs(bfr, state.users[user]):
                    actions.append(Action("add_member", bfr, ("user", user)))
        for sp in spec.get("service_principals", []):
            if sp in state.ambiguous_sps:
                ids = ", ".join(state.ambiguous_sps[sp])
                ambiguous.append(f"service principal {sp} (BFR {bfr}) matches "
                                 f"{len(state.ambiguous_sps[sp])} service principals (ids {ids})")
            elif sp not in state.sps:
                missing.append(f"service principal {sp} (BFR {bfr})")
            elif needs(bfr, state.sps[sp]):
                actions.append(Action("add_member", bfr, ("sp", sp)))
    # 3. BFRs nested INTO OARs — the OAR is the parent group
    for bfr, spec in bfrs.items():
        for oar in spec.get("member_of", []):
            if needs(oar, state.groups.get(bfr)):
                actions.append(Action("add_member", oar, ("group", bfr)))
    # 4. grants to OARs (GRANT of an existing privilege is a no-op)
    for scope, tiers in rm["oars"].items():
        for tier in tiers:
            for stmt in grant_statements(rm, scope, tier):
                actions.append(Action("grant", rm["scopes"][scope][1], sql=stmt))
    # 5. ownership to owner OARs (gated behind --transfer-ownership)
    for scope, tiers in rm["oars"].items():
        if "owner" in tiers:
            kind, full = rm["scopes"][scope]
            stmt = f"ALTER {kind} {q(full)} OWNER TO {q(oar_name(scope, 'owner'))}"
            actions.append(Action("ownership", full, sql=stmt))
    return actions, missing, ambiguous


def gate(action: Action, apply: bool, transfer_ownership: bool) -> bool:
    """Per-mutation-class gate: does this action execute under these flags?"""
    if not apply:
        return False
    if action.kind == "ownership":
        return transfer_ownership
    return True


def render_plan(
    actions: list[Action], missing: list[str], ambiguous: list[str], apply: bool, transfer_ownership: bool
) -> list[str]:
    mode = "APPLY" if apply else "DRY RUN (pass --apply to execute)"
    lines = [f"== mode: {mode}{' + transfer-ownership' if transfer_ownership else ''} =="]
    for a in actions:
        held = "" if gate(a, True, transfer_ownership) else "  [skipped: needs --transfer-ownership]"
        lines.append(a.describe() + held)
    for m in missing:
        lines.append(f"MISSING        {m} — create it at the account level first; skipped")
    for m in ambiguous:
        lines.append(f"AMBIGUOUS      {m} — name it by its applicationId instead; skipped")
    return lines


def execute(actions: list[Action], state: State, backend, apply: bool, transfer_ownership: bool) -> int:
    """Run the gated subset of the plan, resolving names to ids as groups appear."""
    ran = 0
    for a in actions:
        if not gate(a, apply, transfer_ownership):
            continue
        if a.kind == "create_group":
            state.groups[a.target] = backend.create_group(a.target)
        elif a.kind == "add_member":
            kind, name = a.member
            pool = {"user": state.users, "sp": state.sps, "group": state.groups}[kind]
            backend.add_members(state.groups[a.target], [pool[name]])
        else:
            backend.sql(a.sql)
        ran += 1
    return ran


# ---------------------------------------------------------- verification --
def non_oar_grantees(grant_rows: list[list[str]], oars: list[str]) -> list[str]:
    """SHOW GRANTS rows (principal first) whose grantee is not an OAR — each is a defect."""
    allowed = set(oars)
    return sorted({row[0] for row in grant_rows if row and row[0] not in allowed})


def expected_access(rm: dict) -> dict[str, dict[str, str]]:
    """user -> {securable full name: tier} implied by BFR -> OAR nesting."""
    out: dict[str, dict[str, str]] = {}
    tier_of = {oar_name(s, t): (s, t) for s, ts in rm["oars"].items() for t in ts}
    for spec in rm["bfrs"].values():
        for user in spec.get("users") or []:
            for oar in spec.get("member_of", []):
                scope, tier = tier_of[oar]
                if tier in EXPECTED_PRIVILEGES:
                    out.setdefault(user, {})[rm["scopes"][scope][1]] = tier
    return out


def effective_privileges(response: dict) -> set[str]:
    """Flatten an effective-permissions API response into privilege names."""
    privs: set[str] = set()
    for assignment in response.get("privilege_assignments", []):
        for p in assignment.get("privileges", []):
            name = p.get("privilege", "") if isinstance(p, dict) else str(p)
            privs.add(name.upper().replace(" ", "_"))
    return privs


def access_gaps(tier: str, observed: set[str]) -> set[str]:
    return EXPECTED_PRIVILEGES[tier] - observed


# ------------------------------------------------------------- backend --
class CliBackend:
    """Thin `databricks` CLI wrapper. Every method maps to one API call."""

    def __init__(self, account_profile: str, workspace_profile: str, warehouse_id: str):
        self.account, self.workspace, self.warehouse = account_profile, workspace_profile, warehouse_id

    def _cli(self, *args: str, profile: str):
        out = subprocess.run(["databricks", "--profile", profile, *args], capture_output=True, text=True)
        if out.returncode != 0:
            sys.exit(f"FAILED: databricks {' '.join(args[:3])} ...\n{out.stderr.strip()}")
        return json.loads(out.stdout) if out.stdout.strip() else {}

    def read_state(self, group_names: list[str]) -> State:
        acct = self.account
        users = self._cli("account", "users", "list", "--output", "json", profile=acct)
        sps = self._cli("account", "service-principals", "list", "--output", "json", profile=acct)
        groups = self._cli("account", "groups", "list", "--output", "json", profile=acct)
        state = State(users={u["userName"]: u["id"] for u in users})
        state.sps, state.ambiguous_sps = index_service_principals(sps)
        state.groups = {g["displayName"]: g["id"] for g in groups}
        for name in group_names:
            if name in state.groups:
                g = self._cli("account", "groups", "get", str(state.groups[name]), profile=acct)
                state.members[name] = {m["value"] for m in g.get("members", [])}
        return state

    def create_group(self, name: str) -> str:
        body = json.dumps({"displayName": name})
        return self._cli("account", "groups", "create", "--json", body, profile=self.account)["id"]

    def add_members(self, group_id: str, member_ids: list[str]) -> None:
        patch = {
            "schemas": ["urn:ietf:params:scim:schemas:api:messages:2.0:PatchOp"],
            "Operations": [{"op": "add", "path": "members", "value": [{"value": m} for m in member_ids]}],
        }
        self._cli("account", "groups", "patch", str(group_id), "--json", json.dumps(patch), profile=self.account)

    def sql(self, statement: str) -> list[list[str]]:
        body = json.dumps({"warehouse_id": self.warehouse, "statement": statement, "wait_timeout": "50s"})
        resp = self._cli("api", "post", "/api/2.0/sql/statements", "--json", body, profile=self.workspace)
        status = resp.get("status", {})
        if status.get("state") != "SUCCEEDED":
            sys.exit(f"SQL {status.get('state')}: {statement}\n{status.get('error', {})}")
        return resp.get("result", {}).get("data_array") or []

    def effective_permissions(self, kind: str, full: str, principal: str) -> dict:
        path = f"/api/2.1/unity-catalog/effective-permissions/{kind.lower()}/{full}?principal={urllib.parse.quote(principal)}"
        return self._cli("api", "get", path, profile=self.workspace)


def offline_state(rm: dict) -> State:
    """Empty account where every named principal exists — shows the full plan, no auth."""
    state = State()
    for spec in rm["bfrs"].values():
        state.users.update({u: f"<{u}>" for u in spec.get("users") or []})
        state.sps.update({s: f"<{s}>" for s in spec.get("service_principals", [])})
    return state


def verify(rm: dict, backend) -> int:
    failures = 0
    oars = oar_names(rm)
    print("== SHOW GRANTS (expect ONLY OAR grantees) ==")
    for kind, full in rm["scopes"].values():
        bad = non_oar_grantees(backend.sql(f"SHOW GRANTS ON {kind} {q(full)}"), oars)
        failures += len(bad)
        print(f"{full}: {'OK' if not bad else 'NON-OAR GRANTEES ' + ', '.join(bad)}")
    print("== effective permissions (proves access confers through the nesting) ==")
    kinds = {full: kind for kind, full in rm["scopes"].values()}
    for user, scopes in expected_access(rm).items():
        for full, tier in scopes.items():
            gaps = access_gaps(tier, effective_privileges(backend.effective_permissions(kinds[full], full, user)))
            failures += bool(gaps)
            print(f"{user} on {full} ({tier}): {'OK' if not gaps else 'MISSING ' + ', '.join(sorted(gaps))}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--apply", action="store_true", help="execute groups, memberships and grants")
    p.add_argument("--transfer-ownership", action="store_true", help="with --apply, also ALTER ... OWNER TO")
    p.add_argument("--verify", action="store_true", help="read-only SHOW GRANTS + effective-permissions check")
    p.add_argument("--offline", action="store_true", help="plan against an empty account; no auth, no calls")
    p.add_argument("--account-profile", default=os.environ.get("RBAC_ACCOUNT_PROFILE"))
    p.add_argument("--workspace-profile", default=os.environ.get("RBAC_WORKSPACE_PROFILE"))
    p.add_argument("--warehouse-id", default=os.environ.get("RBAC_WAREHOUSE_ID"))
    args = p.parse_args(argv)

    rm = role_map()
    errors = validate_role_map(rm)
    if errors:
        print("ROLE MAP INVALID:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    if args.offline:
        if args.apply or args.verify:
            p.error("--offline only plans; drop --apply/--verify")
        actions, missing, ambiguous = build_plan(rm, offline_state(rm))
        print("\n".join(render_plan(actions, missing, ambiguous, False, args.transfer_ownership)))
        return 0
    if not (args.account_profile and args.workspace_profile and args.warehouse_id):
        p.error("need --account-profile, --workspace-profile and --warehouse-id (or RBAC_* env vars)")
    backend = CliBackend(args.account_profile, args.workspace_profile, args.warehouse_id)
    if args.verify:
        return verify(rm, backend)
    state = backend.read_state(oar_names(rm) + list(rm["bfrs"]))
    actions, missing, ambiguous = build_plan(rm, state)
    print("\n".join(render_plan(actions, missing, ambiguous, args.apply, args.transfer_ownership)))
    ran = execute(actions, state, backend, args.apply, args.transfer_ownership)
    print(f"== executed {ran} of {len(actions)} planned actions ==")
    if args.apply:
        print("Next: re-run with --verify.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
