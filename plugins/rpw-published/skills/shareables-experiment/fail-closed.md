# Fail closed: identity and probe guardrails

Reference for the **Fail closed** section of `SKILL.md`. Everything here comes from
`randypitcherii/shareables#46`, a delegated-UDF-privilege experiment whose first run
produced a complete, internally consistent, wrong matrix. Three separate false
positives, each one plausible on its own, each one silent.

The shape of the failure is what matters: **none of these three traps produce an
error.** They produce evidence. A harness that only checks "did the script run and
write a row?" cannot tell a real result from any of them — so the checks below have
to be assertions inside the scripts, not review-time vigilance.

## 1. Unified auth silently picks the wrong identity

**What happened.** The Makefile exported `DATABRICKS_CONFIG_PROFILE`, and the scripts
built a "service principal" client with explicit `client_id` / `client_secret` but no
`auth_type`. The SDK's unified-auth chain resolved the configured profile *first*, so
the low-privilege client authenticated as the human running the experiment. Both the
admin client and the nominally restricted client were the same identity. Every
privilege row then measured the admin's permissions and passed convincingly.

**Two fixes, both required.**

Pin the auth method whenever more than one credential source can be present:

```python
from databricks.sdk import WorkspaceClient

sp = WorkspaceClient(
    host=host,
    client_id=client_id,
    client_secret=client_secret,
    auth_type="oauth-m2m",   # REQUIRED — without it a configured profile can win
)
```

And prove it, rather than trusting it. Every principal calls an identity endpoint, and
the harness refuses to proceed if two supposedly distinct principals resolve to the
same identity:

```python
def assert_distinct_identities(clients: dict) -> dict:
    """clients: {role: WorkspaceClient}. Returns {role: identity}. Raises on collision."""
    identities = {role: c.current_user.me().user_name for role, c in clients.items()}
    if len(set(identities.values())) != len(identities):
        raise RuntimeError(f"identity collision — experiment invalid: {identities}")
    return identities
```

Over SQL the equivalent probe is `SELECT current_user()`, run on the same connection
the experiment's real queries use — not on a separately constructed one, which can
resolve differently.

**Where it belongs:** `_common.py` builds the clients and calls this; `verify.py` prints
the resolved identity per role; the results writer refuses to write
`results/matrix_results.json` unless the assertion has passed in this process. Record
the resolved identities *in* the results file so a reader can audit which principal
produced which row.

## 2. `401` is not "unreachable"

**What happened.** The reachability probe wrapped the request in `try/except HTTPError`
and scored any exception as a connectivity failure. A live `401` from a route that was
working perfectly got recorded as "network blocked" — the opposite conclusion, and one
that made a real authorization finding invisible.

**The rule:** any valid HTTP response proves the route completed. Reachability and
authorization are different measurements and belong in different fields.

```python
def probe(url: str) -> dict:
    try:
        r = requests.get(url, timeout=10)
    except requests.exceptions.RequestException as e:
        # Transport only: DNS, TLS, connect timeout, refused
        return {"reachable": False, "transport_error": type(e).__name__}
    # Got bytes back — the route works. 401/403 are *findings*, not failures.
    return {"reachable": True, "status": r.status_code,
            "authorized": r.status_code not in (401, 403)}
```

Use `raise_for_status()` nowhere in a probe. It converts the measurement into an
exception and throws away the distinction you are trying to make. Report the status
code in the matrix notes — "reachable, `403 PERMISSION_DENIED`" is a much stronger
result than "❌ blocked".

## 3. Namespace prefixes are not credentials

**What happened.** The ambient-credential probe scanned the environment for anything
matching `DATABRICKS_*` and concluded credentials were present. The match was
`DATABRICKS_ROOT_VIRTUALENV_ENV` — a virtualenv path set by the runtime, carrying no
authentication material at all. The row claiming "ambient credentials available in this
context" was measuring a path string.

**The rule:** detect credentials semantically. Allowlist the keys that actually carry
authentication material, or skip the inference entirely and prove authentication with a
real request.

```python
CREDENTIAL_KEYS = frozenset({
    "DATABRICKS_TOKEN", "DATABRICKS_CLIENT_ID", "DATABRICKS_CLIENT_SECRET",
    "DATABRICKS_PASSWORD", "DATABRICKS_CONFIG_PROFILE", "DATABRICKS_HOST",
})

def ambient_credentials() -> list[str]:
    """Names only — never values, they end up in committed results/."""
    return sorted(k for k in os.environ if k in CREDENTIAL_KEYS)
```

Widen the allowlist deliberately when the experiment needs another source (cloud
credentials, an OIDC token path). Never widen it to a prefix. And prefer the stronger
evidence where you can get it: an authenticated call that succeeds proves credentials
exist in a way that no environment scan does.

## The gate in `verify.py`

`make verify` is where all of this converges — one real call, and the identity story
proven before a single matrix row exists:

1. Build every principal's client with an explicit `auth_type`.
2. Print the resolved identity for each (`current_user`) and assert they are distinct.
3. Make one real request per principal and print route, identity, status code.
4. Report ambient credentials by allowlisted key name.
5. Exit non-zero on any identity collision — `results/` stays untouched.

## Review checklist

Before an experiment's results are believed — by a reviewer, or by the agent that
produced them:

- [ ] Every SDK client that carries explicit credentials also pins `auth_type`.
- [ ] Multi-principal experiments assert distinct identities and **fail closed** —
      no results written on collision.
- [ ] `results/matrix_results.json` records the identity that produced each row.
- [ ] No probe treats an HTTP status code as a transport failure; `401`/`403` are
      recorded as authorization outcomes with the code.
- [ ] Credential detection uses an allowlist or a real authenticated request — never a
      `DATABRICKS_*`-style prefix match.
- [ ] Identity values in committed artifacts are placeholders or non-identifying (the
      repo is public); credential *values* never appear at all.
