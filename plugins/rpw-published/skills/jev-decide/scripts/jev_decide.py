#!/usr/bin/env python3
"""jev-decide — typed, calibrated decisions from a System One model (OpenJev / Jev).

Stdlib only. Run with ``uv run --no-project python jev_decide.py <command> ...``.

    ask      one state, one question set (a file or inline flags) -> answers
    session  classify Omnigent sessions: observations from the model, policy in code
    eval     score a question set against labeled cases: accuracy, coverage, Brier, ECE
    doctor   which transport resolved, and one tiny live call

Why it is shaped this way (measured, see SKILL.md):

* **Observations, not policy.** The model answers questions about what the state SAYS
  (is it asking the human something? did it claim it is done?). What to DO about that —
  resume, archive, relaunch — is a rule table in code over those answers plus hard facts.
  Asked "what should the manager do next?", the 4B model said ``resume`` for sessions
  that were plainly waiting on a human.
* **Order-stability check.** Reversing a choice question's option order flipped 4 of 10
  live answers, one of them at 0.69 confidence. Every choice/score question is asked twice
  in the SAME call — forward and reversed. ``--debias check`` (the default) keeps the
  forward answer and turns it ``unsure`` when the two orders disagree; ``permute`` averages
  the two distributions instead (it scored worse on the live session set: the reversed order
  of an authored list is a worse prior, not a neutral one); ``off`` sends no twins.
* **Abstention is an answer.** Below the threshold the answer is the string ``"unsure"``,
  never a coin-flip label. Downstream code routes unsure to a human or a bigger model.

Transport (first that resolves): ``--base-url``/``JEV_DECIDE_BASE_URL`` (no auth, e.g. a
local LLM proxy) -> ``--profile`` (direct to the workspace via the ``databricks`` CLI) ->
the rpw LLM proxy recorded in ``~/.rpw/ports.json`` -> ``DATABRICKS_HOST`` +
``DATABRICKS_TOKEN`` -> the ``DEFAULT`` CLI profile.
"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

SYSTEM_ONE_PATH = "/ai-gateway/typesafe/v1/systemone"
DEFAULT_MODEL = "system.ai.openjev-qwen35-4b"
#: The default ``--model``: the best System One model discovery finds, else ``DEFAULT_MODEL``.
#: Preference is measured (8 labeled Omnigent sessions, 2026-10-19): TypeSafe Jev 1.14.0 got
#: 8/8 actions vs OpenJev's 7/8, phase coverage 0.88 vs 0.50, lower Brier on every question,
#: and a lower median latency — but it is served only where the account preview is on.
AUTO_MODEL = "auto"
DEFAULT_THRESHOLD = 0.6
DEFAULT_TIMEOUT = 30.0
REV_SUFFIX = "__rev"
UNSURE = "unsure"
QUESTION_TYPES = ("noul", "choice", "score")
#: Keys System One accepts on a question; set-file extras (``abstain_below``) are stripped.
WIRE_KEYS = ("type", "instructions", "criteria")

EXIT_OK, EXIT_USAGE, EXIT_TRANSPORT, EXIT_BAD_RESPONSE, EXIT_UNSURE = 0, 2, 3, 4, 10


# ----------------------------------------------------------------------------- errors


class DecideError(Exception):
    """A classified failure carrying a ``{code, message, hint}`` envelope."""

    def __init__(self, code: str, message: str, hint: str = "", exit_code: int = EXIT_TRANSPORT):
        super().__init__(message)
        self.code, self.message, self.hint, self.exit_code = code, message, hint, exit_code

    def envelope(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message, "hint": self.hint}}


class TransportError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status, self.message = status, message


# -------------------------------------------------------------------------- transport

#: ``(url, headers, body, timeout) -> decoded JSON``; raises TransportError / OSError.
Post = Callable[[str, Mapping[str, str], Mapping[str, Any], float], Mapping[str, Any]]
#: ``(url, headers, timeout) -> decoded JSON``; the discovery seam.
Get = Callable[[str, Mapping[str, str], float], Mapping[str, Any]]

DECISION_MODELS_PATH = "/__rpw_llm_proxy__/decision-models"
INVENTORY_PATH = "/api/2.0/serving-endpoints"
SYSTEM_ONE_TASK = "llm/v1/systemone"
_FQN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")


def http_get(url: str, headers: Mapping[str, str], timeout: float) -> Mapping[str, Any]:
    req = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — https or loopback
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600] if exc.fp else str(exc.reason)
        raise TransportError(exc.code, detail) from exc


def http_post(url: str, headers: Mapping[str, str], body: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — https or loopback
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600] if exc.fp else str(exc.reason)
        raise TransportError(exc.code, detail) from exc


@dataclass
class Endpoint:
    base_url: str
    headers: dict[str, str]
    source: str  # human-readable: where it resolved from (never the token)

    @property
    def url(self) -> str:
        return self.base_url.rstrip("/") + SYSTEM_ONE_PATH


def _ports_registry() -> Path:
    return Path(os.environ.get("RPW_PORT_REGISTRY") or Path.home() / ".rpw" / "ports.json")


def proxy_from_registry(app_env: str | None = None) -> Endpoint | None:
    """The rpw LLM proxy's recorded listener, if one is recorded. No auth: it is loopback."""
    try:
        data = json.loads(_ports_registry().read_text())
    except (OSError, ValueError):
        return None
    env = app_env or os.environ.get("RPW_LLM_PROXY_ENV") or "prod"
    rec = data.get(f"llm-proxy.listener.{env}") if isinstance(data, dict) else None
    if not isinstance(rec, dict) or not rec.get("port"):
        return None
    host = rec.get("host") or "127.0.0.1"
    return Endpoint(f"http://{host}:{rec['port']}", {}, f"rpw llm proxy ({env}, port {rec['port']})")


def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=60)  # noqa: S603
    except (OSError, subprocess.SubprocessError) as exc:
        raise DecideError("auth_unavailable", f"{argv[0]} failed: {exc}", "Install the databricks CLI or pass --base-url.") from exc
    if done.returncode != 0:
        raise DecideError(
            "auth_expired",
            (done.stderr or done.stdout).strip()[:400] or f"{' '.join(argv[:3])} exited {done.returncode}",
            f"Run: databricks auth login -p {argv[-1]}",
        )
    return done.stdout


def _profile_host(profile: str) -> str | None:
    cfg = configparser.ConfigParser()
    cfg.read(os.environ.get("DATABRICKS_CONFIG_FILE") or Path.home() / ".databrickscfg")
    if profile in cfg and cfg[profile].get("host"):
        return cfg[profile]["host"]
    return None


def direct_from_profile(profile: str) -> Endpoint:
    host = _profile_host(profile)
    if not host:
        env = json.loads(_run(["databricks", "auth", "env", "-p", profile]) or "{}")
        host = (env.get("env") or {}).get("DATABRICKS_HOST")
    if not host:
        raise DecideError("auth_unavailable", f"profile {profile!r} has no host", "Check ~/.databrickscfg.")
    token = json.loads(_run(["databricks", "auth", "token", "-p", profile])).get("access_token")
    if not token:
        raise DecideError("auth_expired", f"no access_token for profile {profile!r}", f"databricks auth login -p {profile}")
    return Endpoint(host, {"Authorization": f"Bearer {token}"}, f"workspace via profile {profile}")


def resolve_endpoints(base_url: str | None = None, profile: str | None = None) -> list[Endpoint]:
    """Candidate endpoints in priority order. Auth-requiring ones are built lazily."""
    base = base_url or os.environ.get("JEV_DECIDE_BASE_URL")
    if base:
        return [Endpoint(base, {}, f"base url {base}")]
    if profile:
        return [direct_from_profile(profile)]
    out: list[Endpoint] = []
    proxy = proxy_from_registry()
    if proxy:
        out.append(proxy)
    if os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"):
        out.append(
            Endpoint(os.environ["DATABRICKS_HOST"], {"Authorization": f"Bearer {os.environ['DATABRICKS_TOKEN']}"}, "DATABRICKS_HOST/TOKEN env")
        )
    out.append(Endpoint("", {}, "profile DEFAULT"))  # placeholder, resolved on use
    return out


class Client:
    """One System One caller. ``post`` is the test seam."""

    def __init__(self, endpoints: list[Endpoint] | None = None, *, post: Post | None = None,
                 timeout: float = DEFAULT_TIMEOUT, model: str | None = None, get: Get | None = None):
        self._endpoints = endpoints
        self.post = post or http_post
        self.get = get or http_get
        self.timeout = timeout
        self.model = model or os.environ.get("JEV_DECIDE_MODEL") or AUTO_MODEL
        self.model_selection: str | None = None
        self._resolve_lock = threading.Lock()  # `session` resolves from parallel threads
        self.used: Endpoint | None = None

    def _candidates(self) -> list[Endpoint]:
        if self._endpoints is None:
            self._endpoints = resolve_endpoints()
        return self._endpoints

    def discover(self) -> list[dict[str, Any]]:
        """System One models reachable through the first endpoint that answers (#2383).

        Through an rpw LLM proxy: its pool-wide ``decision-models`` route (every workspace,
        with the members serving each model). Direct to a workspace: that workspace's own
        inventory, filtered to ``task: llm/v1/systemone``.
        """
        last: Exception | None = None
        for ep in self._candidates():
            if not ep.base_url:
                try:
                    ep = direct_from_profile("DEFAULT")
                except DecideError as exc:
                    last = exc
                    continue
            try:
                if not ep.headers:  # unauthenticated = a proxy in front of the pool
                    try:
                        data = self.get(ep.base_url.rstrip("/") + DECISION_MODELS_PATH, {}, self.timeout)
                        return [dict(m) for m in data.get("models") or [] if isinstance(m, Mapping)]
                    except TransportError as exc:
                        if exc.status != 404:
                            raise
                    # A proxy that predates the pool-wide route: its relay still answers the
                    # inventory, from whichever ONE member the rotation picks.
                    return inventory_models(
                        self.get(ep.base_url.rstrip("/") + INVENTORY_PATH, {}, self.timeout),
                        "one pool member (proxy has no decision-models route; upgrade it)")
                return inventory_models(self.get(ep.base_url.rstrip("/") + INVENTORY_PATH, ep.headers, self.timeout),
                                        ep.source)
            except TransportError as exc:
                raise _classify_transport(exc) from exc
            except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
                last = exc
        if isinstance(last, DecideError):
            raise last
        raise DecideError("unreachable", f"no endpoint answered discovery ({last})",
                          "Start the rpw LLM proxy, pass --base-url, or pass --profile.")

    def resolve_model(self) -> str:
        with self._resolve_lock:
            return self._resolve_model()

    def _resolve_model(self) -> str:
        """A full ``catalog.schema.model`` name passes through; a short name is matched against
        discovery: exact last segment, then a whole hyphen token, then a unique substring."""
        if _FQN.match(self.model):
            return self.model
        if self.model == AUTO_MODEL:
            try:
                names = [str(m.get("model")) for m in self.discover() if m.get("model")]
            except DecideError as exc:
                names, why = [], f"discovery failed ({exc.code})"
            else:
                why = "discovered"
            self.model = pick_auto(names) or DEFAULT_MODEL
            self.model_selection = f"auto: {why}, chose {self.model}"
            return self.model
        want = self.model.lower()
        names = [str(m.get("model")) for m in self.discover() if m.get("model")]
        last = {n: n.split(".")[-1].lower() for n in names}
        hits = ([n for n in names if last[n] == want]
                or [n for n in names if want in last[n].split("-")]  # 'jev' is a token of typesafeai-jev-1-14-0
                or [n for n in names if want in last[n]])  # ...but only a substring of openjev
        if len(hits) == 1:
            self.model = hits[0]
            return self.model
        raise DecideError("model_ambiguous" if hits else "model_not_found",
                          f"{self.model!r} matches {hits or 'no discovered model'}",
                          f"Pass a full name; discovered: {', '.join(names) or 'none'}", EXIT_USAGE)

    def call(self, state: Any, questions: Mapping[str, Any]) -> tuple[Mapping[str, Any], int]:
        body = {"model": self.resolve_model(), "state": state, "questions": questions}
        last: Exception | None = None
        for ep in self._candidates():
            if not ep.base_url:  # lazy DEFAULT profile
                try:
                    ep = direct_from_profile("DEFAULT")
                except DecideError as exc:
                    last = exc
                    continue
            started = time.monotonic()
            try:
                resp = self.post(ep.url, ep.headers, body, self.timeout)
            except TransportError as exc:
                raise _classify_transport(exc) from exc
            except (urllib.error.URLError, ConnectionError) as exc:
                last = exc  # unreachable (e.g. proxy not running): try the next candidate
                continue
            except TimeoutError as exc:
                raise DecideError("timeout", f"System One call timed out after {self.timeout}s", "Raise --timeout or retry.") from exc
            self.used = ep
            return resp, int((time.monotonic() - started) * 1000)
        if isinstance(last, DecideError):
            raise last
        raise DecideError("unreachable", f"no System One endpoint reachable ({last})",
                          "Start the rpw LLM proxy, pass --base-url, or pass --profile.")


def callable_name(endpoint_name: str) -> str | None:
    """``databricks-X`` -> ``system.ai.X``: the name the System One route accepts.

    Mirrors ``rpw_llm_proxy.uc_names.uc_model_name`` (this script is stdlib-only and cannot
    import it). ``foundation_model.name`` is NOT that name for every model: OpenJev's says
    ``system.ai.databricks-openjev-qwen35-4b``, which 404s (measured 2026-10-19).
    """
    prefix = "databricks-"
    return "system.ai." + endpoint_name[len(prefix):] if endpoint_name.startswith(prefix) and len(endpoint_name) > len(prefix) else None


def pick_auto(names: Iterable[str]) -> str | None:
    """TypeSafe Jev (newest version) over OpenJev over anything else System One."""
    names = sorted(set(names), reverse=True)  # 'jev-1-15' sorts before 'jev-1-14'
    jev = [n for n in names if "jev" in n.split(".")[-1].split("-") and "openjev" not in n]
    openjev = [n for n in names if "openjev" in n]
    return (jev or openjev or names or [None])[0]


def inventory_models(payload: Mapping[str, Any], source: str) -> list[dict[str, Any]]:
    """Decision models in one workspace inventory, in the proxy route's shape."""
    out = []
    for ep in payload.get("endpoints") or []:
        if not isinstance(ep, Mapping) or ep.get("task") != SYSTEM_ONE_TASK:
            continue
        if (ep.get("state") or {}).get("ready") != "READY":
            continue
        fqn = callable_name(str(ep.get("name") or ""))
        if not fqn:
            continue
        ents = (ep.get("config") or {}).get("served_entities") or [{}]
        fm = (ents[0].get("foundation_model") or {}) if isinstance(ents[0], Mapping) else {}
        out.append({"model": fqn, "display_name": fm.get("display_name") or fqn,
                    "endpoint": ep.get("name"), "members": [source]})
    return out


def _classify_transport(exc: TransportError) -> DecideError:
    if exc.status in (401, 403):
        return DecideError("auth_expired", exc.message, "Re-authenticate the Databricks profile.")
    if exc.status in (400, 404, 422):
        return DecideError("invalid_request", exc.message,
                           "System One rejected the request: check the model FQN (system.ai.…) and question shapes.",
                           EXIT_USAGE)
    if exc.status == 429:
        return DecideError("rate_limited", exc.message, "Back off and retry.")
    return DecideError("http_error", exc.message, "Retry later.")


# ---------------------------------------------------------------------- question sets


@dataclass
class QuestionSet:
    name: str
    questions: dict[str, dict[str, Any]]
    version: str = "1"
    thresholds: dict[str, float] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.questions:
            raise DecideError("invalid_question_set", "no questions", exit_code=EXIT_USAGE)
        for qid, q in self.questions.items():
            kind = q.get("type")
            if kind not in QUESTION_TYPES:
                raise DecideError("invalid_question_set", f"{qid}: type must be one of {QUESTION_TYPES}", exit_code=EXIT_USAGE)
            crit = q.get("criteria")
            if kind == "choice" and not (isinstance(crit, dict) and 1 <= len(crit) <= 255):
                raise DecideError("invalid_question_set", f"{qid}: choice needs 1-255 criteria", exit_code=EXIT_USAGE)
            if kind == "score" and not (isinstance(crit, list) and 1 <= len(crit) <= 10):
                raise DecideError("invalid_question_set", f"{qid}: score needs a 1-10 level list", exit_code=EXIT_USAGE)
            if qid.endswith(REV_SUFFIX):
                raise DecideError("invalid_question_set", f"{qid}: ids ending {REV_SUFFIX} are reserved", exit_code=EXIT_USAGE)

    def threshold(self, qid: str, default: float) -> float:
        return self.thresholds.get(qid, default)


def load_question_set(path: str) -> QuestionSet:
    data = json.loads(Path(path).read_text())
    qs = data.get("questions") if isinstance(data, dict) and "questions" in data else data
    if not isinstance(qs, dict):
        raise DecideError("invalid_question_set", f"{path}: expected an object of questions", exit_code=EXIT_USAGE)
    thresholds = {qid: float(q["abstain_below"]) for qid, q in qs.items() if isinstance(q, dict) and "abstain_below" in q}
    clean = {qid: {k: v for k, v in q.items() if k in WIRE_KEYS} for qid, q in qs.items()}
    out = QuestionSet(str(data.get("name") or Path(path).stem), clean, str(data.get("version") or "1"), thresholds)
    out.validate()
    return out


def parse_inline(noul: Iterable[str], choice: Iterable[str], score: Iterable[str]) -> dict[str, dict[str, Any]]:
    """``ID=question`` / ``ID=question:opt1|opt2`` / ``ID=question:low|mid|high``."""
    out: dict[str, dict[str, Any]] = {}

    def split(spec: str) -> tuple[str, str]:
        qid, sep, rest = spec.partition("=")
        if not sep or not qid.strip() or not rest.strip():
            raise DecideError("invalid_question", f"expected ID=TEXT, got {spec!r}", exit_code=EXIT_USAGE)
        return qid.strip(), rest.strip()

    for spec in noul:
        qid, text = split(spec)
        out[qid] = {"type": "noul", "instructions": text}
    for kind, specs in (("choice", choice), ("score", score)):
        for spec in specs:
            qid, rest = split(spec)
            text, sep, opts = rest.rpartition(":")
            options = [o.strip() for o in opts.split("|") if o.strip()]
            if not sep or len(options) < 2:
                raise DecideError("invalid_question", f"{qid}: expected TEXT:opt1|opt2[|...]", exit_code=EXIT_USAGE)
            out[qid] = {"type": kind, "instructions": text.strip(),
                        "criteria": {o: None for o in options} if kind == "choice" else options}
    return out


def with_permutations(questions: Mapping[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Add a reversed-order twin for every choice/score question (asked in the same call)."""
    out = dict(questions)
    for qid, q in questions.items():
        if q["type"] == "choice" and len(q["criteria"]) > 1:
            out[qid + REV_SUFFIX] = {**q, "criteria": dict(reversed(list(q["criteria"].items())))}
        elif q["type"] == "score" and len(q["criteria"]) > 1:
            out[qid + REV_SUFFIX] = {**q, "criteria": list(reversed(q["criteria"]))}
    return out


# ------------------------------------------------------------------------- answers


def _argmax(dist: Mapping[str, float]) -> str | None:
    return max(dist, key=dist.__getitem__) if dist else None


def _dist(kind: str, q: Mapping[str, Any], raw: Mapping[str, Any], *, reversed_: bool = False) -> dict[str, float]:
    """A label -> probability distribution, in the FORWARD question's label space."""
    if kind == "noul":
        p = float(raw["noul"])
        return {"true": p, "false": 1.0 - p}
    if kind == "choice":
        probs = raw.get("probabilities") or {}
        if not probs and raw.get("choice") is not None:
            probs = {str(raw["choice"]): float(raw.get("confidence") or 1.0)}
        return {str(k): float(v) for k, v in probs.items()}
    levels = list(q["criteria"])
    if reversed_:
        levels = list(reversed(levels))
    legend = raw.get("legend") or {}
    out: dict[str, float] = {}
    for idx, p in (raw.get("probabilities") or {}).items():
        label = legend.get(str(idx)) or levels[int(idx)]
        out[str(label)] = float(p)
    return out


def interpret(
    qset: QuestionSet, response: Mapping[str, Any], *, threshold: float = DEFAULT_THRESHOLD,
    disagreement_is_unsure: bool = True, average: bool = False,
) -> dict[str, dict[str, Any]]:
    """Normalize a System One response, merging permutation twins and applying abstention."""
    answers = response.get("answers") if isinstance(response, Mapping) else None
    if not isinstance(answers, Mapping):
        raise DecideError("bad_response", "System One response has no 'answers' object", exit_code=EXIT_BAD_RESPONSE)
    out: dict[str, dict[str, Any]] = {}
    for qid, q in qset.questions.items():
        kind = q["type"]
        raw = answers.get(qid)
        if not isinstance(raw, Mapping):
            raise DecideError("bad_response", f"no answer for {qid!r}", exit_code=EXIT_BAD_RESPONSE)
        try:
            dist = _dist(kind, q, raw)
            twin = answers.get(qid + REV_SUFFIX)
            agreement = None
            if isinstance(twin, Mapping):
                rdist = _dist(kind, q, twin, reversed_=True)
                agreement = _argmax(dist) == _argmax(rdist)
                if average:
                    keys = set(dist) | set(rdist)
                    dist = {k: (dist.get(k, 0.0) + rdist.get(k, 0.0)) / 2 for k in keys}
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise DecideError("bad_response", f"unparseable {kind} answer for {qid!r}: {exc}", exit_code=EXIT_BAD_RESPONSE) from exc
        best = _argmax(dist)
        confidence = dist.get(best, 0.0) if best is not None else 0.0
        limit = qset.threshold(qid, threshold)
        unsure_reason = None
        if confidence < limit:
            unsure_reason = f"confidence {confidence:.2f} < {limit:.2f}"
        elif agreement is False and disagreement_is_unsure:
            unsure_reason = "forward and reversed option order disagree"
        if kind == "noul":
            label: Any = best == "true"
        else:
            label = best
        entry: dict[str, Any] = {
            "type": kind,
            "answer": UNSURE if unsure_reason else label,
            "best_guess": label,
            "confidence": round(confidence, 4),
            "probabilities": {k: round(v, 4) for k, v in sorted(dist.items(), key=lambda kv: -kv[1])},
        }
        if kind == "noul":
            entry["p_true"] = round(dist["true"], 4)
        if kind == "score":
            levels = list(q["criteria"])
            entry["score"] = round(sum(levels.index(k) * v for k, v in dist.items() if k in levels), 4)
        if agreement is not None:
            entry["order_agreement"] = agreement
        if unsure_reason:
            entry["unsure_reason"] = unsure_reason
        out[qid] = entry
    return out


@dataclass
class Decision:
    answers: dict[str, dict[str, Any]]
    model: str
    latency_ms: int
    usage: dict[str, Any] | None
    endpoint: str
    model_selection: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {"ok": True, "model": self.model, "latency_ms": self.latency_ms, "usage": self.usage,
               "endpoint": self.endpoint, "answers": self.answers}
        if self.model_selection:
            out["model_selection"] = self.model_selection
        return out

    @property
    def any_unsure(self) -> bool:
        return any(a["answer"] == UNSURE for a in self.answers.values())


DEBIAS_MODES = ("check", "permute", "off")


def decide(client: Client, qset: QuestionSet, state: Any, *, debias: str = "check",
           threshold: float = DEFAULT_THRESHOLD, disagreement_is_unsure: bool = True) -> Decision:
    if debias not in DEBIAS_MODES:
        raise DecideError("usage", f"debias must be one of {DEBIAS_MODES}", exit_code=EXIT_USAGE)
    wire = dict(qset.questions) if debias == "off" else with_permutations(qset.questions)
    resp, ms = client.call(state, wire)
    answers = interpret(qset, resp, threshold=threshold, disagreement_is_unsure=disagreement_is_unsure,
                        average=debias == "permute")
    usage = resp.get("usage") if isinstance(resp.get("usage"), Mapping) else None
    return Decision(answers, client.model, ms, dict(usage) if usage else None,
                    client.used.source if client.used else "?", client.model_selection)


# ----------------------------------------------------------------- omnigent sessions

#: Observations only. Every question is about what the transcript SAYS; none asks what to do.
SESSION_QUESTIONS = QuestionSet(
    name="omnigent-session",
    version="1",
    questions={
        "phase": {
            "type": "choice",
            "instructions": "Judging by the most recent messages, what state is this agent session in?",
            "criteria": {
                "working": "it is running tools and making progress on its own",
                "waiting_on_background": "it started a build, test, deploy, or monitor and is waiting for it; no human needed",
                "waiting_on_human": "it stopped and needs the human to answer, decide, approve, log in, or run something",
                "blocked_external": "it cannot continue because of something outside its control, such as a limit, outage, or missing access",
                "finished": "it reported the task complete and asked for nothing",
                "errored": "the session crashed or shows only errors",
                "never_started": "there is only the initial request and no work",
            },
        },
        "asks_human": {
            "type": "noul",
            "instructions": "Does the latest assistant message ask the human to do, decide, approve, or answer something?",
            "criteria": {"true": "it asks the human for an action, decision, approval, or answer",
                         "false": "it asks the human for nothing"},
        },
        "claims_complete": {
            "type": "noul",
            "instructions": "Does the agent say its whole task is done?",
            "criteria": {"true": "it says the task is complete or finished",
                         "false": "it says work remains, or says nothing about completion"},
        },
        "shipped": {
            "type": "choice",
            "instructions": "What has this session delivered so far, according to its messages?",
            "criteria": {
                "merged_or_deployed": "a pull request was merged, or a change was deployed or released",
                "pr_open": "a pull request is open but not merged",
                "committed_unpushed": "commits exist but no pull request was opened",
                "non_code_deliverable": "it delivered a document, report, comment, or answer rather than code",
                "nothing": "nothing has been delivered yet",
            },
        },
        "looping": {
            "type": "noul",
            "instructions": "Is the agent repeating the same failing step or the same message without progress?",
            "criteria": {"true": "it repeats the same failing action or message", "false": "it is not repeating itself"},
        },
        "human_frustrated": {
            "type": "noul",
            "instructions": "Did the human express frustration or repeat an instruction the agent ignored?",
            "criteria": {"true": "the human is frustrated or repeating themselves", "false": "no sign of frustration"},
        },
    },
)

STALE_MINUTES = 30
_SECRET = re.compile(r"\b(dapi[0-9a-f]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_.-]+)")


def _text(item: Mapping[str, Any]) -> str:
    content = item.get("content")
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for c in content:
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, Mapping) and isinstance(c.get("text"), str):
                parts.append(c["text"])
    for key in ("text", "message"):
        if isinstance(item.get(key), str):
            parts.append(item[key])
    return "\n".join(parts)


def _clip(text: str, n: int) -> str:
    text = _SECRET.sub("[REDACTED]", text.strip())
    return text if len(text) <= n else text[: n // 3] + " … " + text[-(2 * n) // 3 :]


def session_state(record: Mapping[str, Any], *, now: float | None = None, messages: int = 3,
                  max_chars: int = 700) -> dict[str, Any]:
    """The compact state the model reads: hard facts + the last few messages, clipped."""
    now = time.time() if now is None else now
    items = [i for i in (record.get("items") or []) if isinstance(i, Mapping)]
    msgs: list[str] = []
    tool_calls = errors = 0
    for it in items:
        kind = it.get("type")
        if kind in ("function_call", "tool_call"):
            tool_calls += 1
        elif kind == "error":
            errors += 1
            msgs.append("error: (session error)")
        elif kind == "message":
            text = _text(it)
            if text.strip():
                msgs.append(f"{it.get('role') or '?'}: {_clip(text, max_chars)}")
    last = record.get("last_activity_at")
    try:
        idle = max(0, int((now - float(last)) / 60)) if last is not None else None
    except (TypeError, ValueError):
        idle = None
    state = {
        "title": record.get("title"),
        "status": record.get("status"),
        "runner_online": record.get("runner_online"),
        "idle_minutes": idle,
        "pending_questions": record.get("pending_elicitation_count") or len(record.get("pending_elicitations") or []) or None,
        "recent_tool_calls": tool_calls or None,
        "recent_errors": errors or None,
        "workspace_git": record.get("workspace_git"),
        "recent_messages": msgs[-messages:] or None,
    }
    return {k: v for k, v in state.items() if v is not None}


@dataclass
class SessionVerdict:
    session_id: str
    title: str
    action: str
    why: str
    flags: list[str]
    facts: dict[str, Any]
    answers: dict[str, dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "title": self.title, "action": self.action, "why": self.why,
                "flags": self.flags, "facts": self.facts,
                "answers": {k: {"answer": v["answer"], "confidence": v["confidence"],
                                **({"unsure_reason": v["unsure_reason"]} if "unsure_reason" in v else {})}
                            for k, v in self.answers.items()}}


#: Actions, most urgent first. ``archive`` and ``clean_up`` come ONLY from the record's
#: ``delivery`` fact (``rpw sessions classify`` reads it from `git` + `gh`, #2449): completion
#: is an artifact `gh` confirms, never a model's say-so. Without that fact the most a finished
#: session earns is ``verify_then_archive``.
ACTIONS = ("relaunch", "answer_human", "intervene", "review", "resume", "nudge",
           "track_pr", "clean_up", "verify_then_archive", "archive", "leave_alone")

#: ``delivery.state`` values that are artifact-verified merges.
_MERGED = ("shipped", "cleanup-pending")


def _wip(git: Any) -> str | None:
    if not isinstance(git, Mapping) or git.get("error"):
        return None
    bits = []
    if git.get("dirty_files"):
        bits.append(f"{git['dirty_files']} uncommitted file(s)")
    if "upstream" in git and not git.get("upstream") and not git.get("pr"):
        bits.append("branch never pushed")
    if git.get("ahead") and not git.get("pr"):
        bits.append(f"{git['ahead']} unpushed commit(s)")
    return "; ".join(bits) or None


def session_policy(record: Mapping[str, Any], answers: Mapping[str, dict[str, Any]] | None,
                   *, stale_minutes: int = STALE_MINUTES, now: float | None = None) -> tuple[str, str, list[str]]:
    """Facts first, then model observations. Returns (action, why, flags). Pure."""
    status = str(record.get("status") or "unknown")
    runner = record.get("runner_online")
    pending = record.get("pending_elicitation_count") or len(record.get("pending_elicitations") or [])
    st = session_state(record, now=now)
    idle = st.get("idle_minutes")
    delivery = record.get("delivery") if isinstance(record.get("delivery"), Mapping) else {}
    dstate, ddetail = delivery.get("state"), delivery.get("detail") or ""
    wip = (ddetail if dstate == "wip" else None) or _wip(record.get("workspace_git"))
    flags: list[str] = []

    # 1. Hard facts the model is never asked about.
    if status == "failed":
        return "relaunch", "status=failed (relaunch in place; keep the worktree)", flags
    if pending:
        return "answer_human", f"{pending} structured question(s) pending", flags
    if answers is None:
        return "review", "no model answers (facts alone cannot settle an idle session)", flags

    a = {k: v["answer"] for k, v in answers.items()}
    if a.get("human_frustrated") is True:
        flags.append("human_frustrated")
    if a.get("looping") is True:
        flags.append("looping")
    phase, shipped = a.get("phase"), a.get("shipped")

    if status == "running":
        if a.get("looping") is True:
            return "intervene", "running but repeating the same step", flags
        return "leave_alone", "status=running", flags

    # 2. Observations, corroborated. Two confident narrow answers outvote one unsure broad one:
    #    "asks you something" beats any phase; "says done + delivered + asks nothing" is finished
    #    even when the 7-way phase question split across option orders (measured live).
    delivered = ("merged_or_deployed", "non_code_deliverable", "pr_open")
    if a.get("asks_human") is True:
        phase = "waiting_on_human"
    elif a.get("claims_complete") is True and a.get("asks_human") is False and shipped in delivered:
        phase = "finished"
    if phase in ("waiting_on_human", "blocked_external"):
        where = "" if runner else " (runner offline: answering it means a relaunch/resume)"
        return "answer_human", f"its last message hands control to you (phase={phase}){where}", flags
    if a.get("looping") is True:
        return "intervene", "idle after repeating the same step without progress", flags
    # 3. Artifact-verified delivery outranks the model's reading of the prose (#2449), unless
    #    the session is still doing something on its own after the merge.
    if dstate in _MERGED and phase not in ("working", "waiting_on_background"):
        if dstate == "shipped":
            return "archive", f"verified shipped: {ddetail}", flags
        return "clean_up", f"merged, but left behind: {ddetail}", flags
    if dstate == "pr-open":
        shipped = "pr_open"
    if phase == UNSURE:
        return "review", f"phase unsure ({answers['phase'].get('unsure_reason')}); best guess {answers['phase']['best_guess']}", flags
    if phase == "errored":
        return "relaunch", "transcript ends in errors", flags
    if phase == "never_started":
        return ("resume" if runner else "relaunch"), "created but never did any work", flags
    if phase == "working":
        return "resume", "the turn ended mid-work with nothing asked of you", flags
    if phase == "waiting_on_background":
        if runner is False:
            return "resume", "was waiting on a background job, but the runner is gone", flags
        if idle is not None and idle > stale_minutes:
            return "nudge", f"waiting on a background job for {idle}m; its watcher may have died", flags
        return "leave_alone", "waiting on its own background job", flags
    # phase == finished (or claims_complete)
    if wip:
        return "resume", f"says finished, but the workspace has WIP: {wip}", flags
    if shipped == "pr_open":
        return "track_pr", "finished with an open PR: merge or watch it", flags
    if shipped in ("merged_or_deployed", "non_code_deliverable"):
        return "verify_then_archive", f"finished and delivered ({shipped}); confirm the artifact, then archive", flags
    if shipped == UNSURE:
        return "review", "finished, but what shipped is unclear", flags
    return "resume", f"says finished but shipped={shipped}: a finished turn is not finished work", flags


def classify_session(client: Client, record: Mapping[str, Any], *, debias: str = "check",
                     threshold: float = DEFAULT_THRESHOLD, now: float | None = None,
                     stale_minutes: int = STALE_MINUTES) -> SessionVerdict:
    sid = str(record.get("session_id") or record.get("id") or record.get("conversation_id") or "?")
    status = str(record.get("status") or "")
    answers = None
    # Facts that settle the verdict on their own cost no model call.
    if status != "failed" and not (record.get("pending_elicitation_count") or record.get("pending_elicitations")):
        answers = decide(client, SESSION_QUESTIONS, session_state(record, now=now), debias=debias,
                         threshold=threshold).answers
    action, why, flags = session_policy(record, answers, stale_minutes=stale_minutes, now=now)
    facts = {k: v for k, v in session_state(record, now=now).items() if k != "recent_messages"}
    return SessionVerdict(sid, str(record.get("title") or ""), action, why, flags, facts, answers or {})


def classify_or_review(client: Client, record: Mapping[str, Any], **kwargs: Any) -> dict[str, Any]:
    """One verdict dict, never a raise: a classifier failure becomes ``review`` with a flag.

    The one row shape ``session`` prints and ``rpw sessions classify`` returns, so the two
    can never disagree about how a failed model call is reported.
    """
    try:
        return classify_session(client, record, **kwargs).to_dict()
    except DecideError as exc:
        return {"session_id": record.get("session_id"), "title": record.get("title"), "action": "review",
                "why": f"classifier failed: {exc.code}: {exc.message}", "flags": ["classifier_error"]}


def load_records(paths: Iterable[str]) -> list[dict[str, Any]]:
    """Session records from fleet-report-style files (see :func:`merge_records`)."""
    return merge_records(json.loads(sys.stdin.read() if path == "-" else Path(path).read_text()) for path in paths)


def merge_records(documents: Iterable[Any]) -> list[dict[str, Any]]:
    """Session records from decoded documents: one object, a list, a wrapper, or an id map.

    A ``sys_session_get_history`` response (``{"conversation_id", "items"}``) merges into the
    matching ``get_info`` record by id, so the two reads can be saved as separate files.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for data in documents:
        if isinstance(data, dict):
            for key in ("data", "sessions", "info"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if isinstance(data, dict) and data and all(isinstance(v, dict) for v in data.values()) and not (
            {"session_id", "conversation_id", "items", "status"} & set(data)
        ):
            data = [{"session_id": k, **v} for k, v in data.items()]
        for rec in data if isinstance(data, list) else [data]:
            if not isinstance(rec, dict):
                continue
            sid = str(rec.get("session_id") or rec.get("id") or rec.get("conversation_id") or f"#{len(by_id)}")
            merged = by_id.setdefault(sid, {"session_id": sid})
            for k, v in rec.items():
                if v is not None and not (k == "title" and merged.get("title")):
                    merged[k] = v
    return list(by_id.values())


def record_from_rest(session: Mapping[str, Any], items: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Map the Omnigent REST shapes onto the ``get_info`` + ``get_history`` record the policy reads.

    ``session`` is ``GET /v1/sessions/{id}``; ``items`` is ``GET /v1/sessions/{id}/items`` in
    chronological order. REST nests an item's role and content under ``data`` and names the
    last activity ``updated_at``; ``sys_session_get_info`` flattens both. This is the ONE place
    that difference is absorbed (#2437), so a live fetch classifies exactly like a saved file.
    """
    pending = session.get("pending_elicitations")
    count = session.get("pending_elicitations_count")
    if count is None:
        count = len(pending) if isinstance(pending, list) else 0
    flat = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        data = item.get("data")
        flat.append({**data, **{k: v for k, v in item.items() if k != "data"}} if isinstance(data, Mapping) else dict(item))
    record = {
        "session_id": session.get("id") or session.get("session_id"),
        "title": session.get("title"),
        "status": session.get("status"),
        "runner_online": session.get("runner_online"),
        "last_activity_at": session.get("updated_at", session.get("last_activity_at")),
        "pending_elicitations": pending if isinstance(pending, list) else [],
        "pending_elicitation_count": count,
        "workspace": session.get("workspace"),
        "git_branch": session.get("git_branch"),
        "items": flat,
    }
    return {k: v for k, v in record.items() if v is not None}


# ------------------------------------------------------------------------------ eval


def _norm_label(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip().lower()


def score_eval(results: list[tuple[Mapping[str, dict[str, Any]], Mapping[str, Any]]], bins: int = 10) -> dict[str, Any]:
    """Per-question accuracy, coverage, Brier and ECE over (answers, expected labels) pairs."""
    per: dict[str, dict[str, Any]] = {}
    for answers, labels in results:
        for qid, expected in labels.items():
            if qid not in answers:
                continue
            a = answers[qid]
            m = per.setdefault(qid, {"n": 0, "answered": 0, "correct": 0, "guess_correct": 0, "brier": 0.0,
                                     "conf": [], "confusions": {}})
            exp = _norm_label(expected)
            guess = _norm_label(a["best_guess"])
            probs = {_norm_label(k): v for k, v in a["probabilities"].items()}
            m["n"] += 1
            m["guess_correct"] += guess == exp
            m["brier"] += sum((p - (1.0 if k == exp else 0.0)) ** 2 for k, p in probs.items()) + (0 if exp in probs else 1)
            m["conf"].append((a["confidence"], guess == exp))
            if a["answer"] != UNSURE:
                m["answered"] += 1
                m["correct"] += guess == exp
            if guess != exp:
                key = f"{exp}->{guess}"
                m["confusions"][key] = m["confusions"].get(key, 0) + 1
    report = {}
    for qid, m in per.items():
        ece = 0.0
        for b in range(bins):
            lo, hi = b / bins, (b + 1) / bins
            cell = [(c, ok) for c, ok in m["conf"] if lo <= c < hi or (b == bins - 1 and c == 1.0)]
            if cell:
                ece += len(cell) / m["n"] * abs(sum(c for c, _ in cell) / len(cell) - sum(ok for _, ok in cell) / len(cell))
        report[qid] = {
            "n": m["n"],
            "accuracy_all": round(m["guess_correct"] / m["n"], 3),
            "coverage": round(m["answered"] / m["n"], 3),
            "accuracy_answered": round(m["correct"] / m["answered"], 3) if m["answered"] else None,
            "brier": round(m["brier"] / m["n"], 4),
            "ece": round(ece, 4),
            "top_confusions": dict(sorted(m["confusions"].items(), key=lambda kv: -kv[1])[:3]),
        }
    return report


# ------------------------------------------------------------------------------- CLI


def _read_state(args: argparse.Namespace) -> Any:
    if args.state is not None and args.state_file:
        raise DecideError("usage", "pass --state or --state-file, not both", exit_code=EXIT_USAGE)
    raw = args.state if args.state is not None else (
        sys.stdin.read() if args.state_file == "-" else Path(args.state_file).read_text() if args.state_file else None)
    if raw is None:
        raise DecideError("usage", "a state is required (--state TEXT or --state-file PATH|-)", exit_code=EXIT_USAGE)
    try:
        return json.loads(raw)
    except ValueError:
        return raw


_GET: list[Get | None] = [None]  # main()'s discovery seam, threaded without touching every command


def _client(args: argparse.Namespace, post: Post | None) -> Client:
    endpoints = resolve_endpoints(args.base_url, args.profile) if (args.base_url or args.profile) else None
    return Client(endpoints, post=post, timeout=args.timeout, model=args.model, get=_GET[0])


def _log(path: str | None, entry: Mapping[str, Any]) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": time.time(), **entry}, default=str) + "\n")


def _qset_from_args(args: argparse.Namespace) -> QuestionSet:
    if args.questions:
        qset = load_question_set(args.questions)
    else:
        qset = QuestionSet("inline", parse_inline(args.noul or [], args.choice or [], args.score or []))
    if args.questions and (args.noul or args.choice or args.score):
        qset.questions.update(parse_inline(args.noul or [], args.choice or [], args.score or []))
    qset.validate()
    return qset


def cmd_ask(args: argparse.Namespace, post: Post | None) -> int:
    qset = _qset_from_args(args)
    state = _read_state(args)
    result = decide(_client(args, post), qset, state, debias=args.debias, threshold=args.threshold,
                    disagreement_is_unsure=not args.allow_disagreement)
    _log(args.log, {"cmd": "ask", "question_set": qset.name, "version": qset.version, "state": state,
                    "answers": result.answers, "model": result.model})
    if args.format == "text":
        for qid, a in result.answers.items():
            extra = f"  ({a['unsure_reason']}; best guess {a['best_guess']})" if a["answer"] == UNSURE else ""
            print(f"{qid}: {a['answer']}  conf={a['confidence']:.2f}{extra}")
        print(f"model={result.model} latency={result.latency_ms}ms via {result.endpoint}")
    else:
        print(json.dumps(result.to_dict(), indent=None if args.compact else 1))
    return EXIT_UNSURE if args.fail_on_unsure and result.any_unsure else EXIT_OK


def cmd_session(args: argparse.Namespace, post: Post | None) -> int:
    records = load_records(args.input)
    client = _client(args, post)

    def one(rec: dict[str, Any]) -> dict[str, Any]:
        return classify_or_review(client, rec, debias=args.debias, threshold=args.threshold,
                                  stale_minutes=args.stale_minutes)

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        verdicts = list(pool.map(one, records))
    order = {a: i for i, a in enumerate(ACTIONS)}
    verdicts.sort(key=lambda v: order.get(v["action"], len(order)))
    for v in verdicts:
        _log(args.log, {"cmd": "session", "verdict": v})
    if args.format == "text":
        counts: dict[str, int] = {}
        for v in verdicts:
            counts[v["action"]] = counts.get(v["action"], 0) + 1
        print(f"sessions: {len(verdicts)}  " + "  ".join(f"{a}={counts[a]}" for a in ACTIONS if a in counts))
        current = None
        for v in verdicts:
            if v["action"] != current:
                current = v["action"]
                print(f"## {current}")
            flags = f"  [{', '.join(v['flags'])}]" if v.get("flags") else ""
            print(f"- {str(v['session_id'])[:12]}  {str(v.get('title') or '')[:70]}{flags}\n    {v['why']}")
    else:
        print(json.dumps({"ok": True, "count": len(verdicts), "verdicts": verdicts}, indent=None if args.compact else 1))
    return EXIT_OK


def cmd_eval(args: argparse.Namespace, post: Post | None) -> int:
    """Cases JSONL: ``{"state": ..., "labels": {qid: expected}}`` — or, with ``--preset
    omnigent-session``, ``{"session": {...record}, "labels": {...}, "action": "..."}``."""
    preset = args.preset == "omnigent-session"
    qset = SESSION_QUESTIONS if preset else _qset_from_args(args)
    cases = [json.loads(line) for line in Path(args.cases).read_text().splitlines() if line.strip()]
    client = _client(args, post)

    def one(case: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str | None]:
        if preset:
            rec = case["session"]
            answers = decide(client, qset, session_state(rec, now=case.get("now")), debias=args.debias,
                             threshold=args.threshold).answers
            action = session_policy(rec, answers, now=case.get("now"))[0]
            return answers, case.get("labels") or {}, action
        return decide(client, qset, case["state"], debias=args.debias,
                      threshold=args.threshold).answers, case.get("labels") or {}, None

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as pool:
        rows = list(pool.map(one, cases))
    report: dict[str, Any] = {"ok": True, "question_set": qset.name, "version": qset.version, "cases": len(cases),
                              "debias": args.debias, "threshold": args.threshold,
                              "questions": score_eval([(a, lab) for a, lab, _ in rows])}
    if preset:
        expected = [(c.get("action"), act) for c, (_, _, act) in zip(cases, rows) if c.get("action")]
        if expected:
            report["action_accuracy"] = round(sum(e == g for e, g in expected) / len(expected), 3)
            report["action_misses"] = [f"{e}->{g}" for e, g in expected if e != g][:10]
    print(json.dumps(report, indent=1))
    return EXIT_OK


def cmd_models(args: argparse.Namespace, post: Post | None) -> int:
    models = _client(args, post).discover()
    if args.format == "text":
        for m in models:
            print(f"{m['model']}  ({m.get('display_name')})  served by {len(m.get('members') or [])}: "
                  f"{', '.join(m.get('members') or [])}")
        if not models:
            print("no System One models discovered")
    else:
        print(json.dumps({"ok": True, "count": len(models), "models": models}, indent=None if args.compact else 1))
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace, post: Post | None) -> int:
    client = _client(args, post)
    qset = QuestionSet("doctor", {"ok": {"type": "noul", "instructions": "Is the sky blue on a clear day?"}})
    result = decide(client, qset, "A clear summer day.", debias="off", threshold=0.0)
    print(json.dumps({"ok": True, "endpoint": result.endpoint, "model": result.model, "latency_ms": result.latency_ms,
                      "usage": result.usage, "sanity_p_true": result.answers["ok"]["p_true"],
                      "fingerprint": hashlib.sha256(client.model.encode()).hexdigest()[:8]}))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="jev_decide", description=__doc__.split("\n\n")[0])
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", help="System One host (no auth), e.g. a local LLM proxy URL")
    common.add_argument("--profile", help="Databricks CLI profile for a direct workspace call")
    common.add_argument("--model", help="full UC name, a short name resolved by discovery ('jev', 'openjev'), or 'auto' "
                        f"(default: Jev if discovered, else {DEFAULT_MODEL}); env JEV_DECIDE_MODEL")
    common.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    common.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="answers below this confidence become 'unsure' (default %(default)s)")
    common.add_argument("--debias", choices=DEBIAS_MODES, default="check",
                        help="ask choice/score questions in both option orders: 'check' = unsure when "
                        "they disagree (default), 'permute' = average them, 'off' = forward only")
    common.add_argument("--format", choices=("json", "text"), default="json")
    common.add_argument("--compact", action="store_true", help="single-line JSON")
    common.add_argument("--log", help="append each decision (with its state) to this JSONL file, for later labeling")
    common.add_argument("--parallel", type=int, default=4)
    qs = argparse.ArgumentParser(add_help=False)
    qs.add_argument("--questions", help="question-set JSON file ({name, version, questions: {...}})")
    qs.add_argument("--noul", action="append", metavar="ID=TEXT", help="yes/no question (repeatable)")
    qs.add_argument("--choice", action="append", metavar="ID=TEXT:a|b|c", help="pick-one question (repeatable)")
    qs.add_argument("--score", action="append", metavar="ID=TEXT:low|mid|high", help="ordered-scale question")

    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ask", parents=[common, qs], help="answer typed questions about one state")
    p.add_argument("--state", help="the state: text, or a JSON object/array")
    p.add_argument("--state-file", help="read the state from a file ('-' = stdin)")
    p.add_argument("--fail-on-unsure", action="store_true", help=f"exit {EXIT_UNSURE} if any answer is unsure")
    p.add_argument("--allow-disagreement", action="store_true",
                   help="keep an answer whose two option orders disagree (default: unsure)")
    p = sub.add_parser("session", parents=[common], help="classify Omnigent sessions -> next action")
    p.add_argument("--input", action="append", required=True,
                   help="get_info/get_history JSON (fleet_report info.json shape); repeatable, '-' = stdin")
    p.add_argument("--stale-minutes", type=int, default=STALE_MINUTES)
    p = sub.add_parser("eval", parents=[common, qs], help="score a question set against labeled JSONL cases")
    p.add_argument("--cases", required=True)
    p.add_argument("--preset", choices=("omnigent-session",))
    sub.add_parser("doctor", parents=[common], help="resolve the transport and make one tiny call")
    sub.add_parser("models", parents=[common],
                   help="list System One models: pool-wide via the LLM proxy, or one workspace's inventory")
    sub.add_parser("questions", help="print the built-in omnigent-session question set")
    return ap


def main(argv: list[str] | None = None, *, post: Post | None = None, get: Get | None = None) -> int:
    args = build_parser().parse_args(argv)
    _GET[0] = get
    try:
        if args.command == "questions":
            print(json.dumps({"name": SESSION_QUESTIONS.name, "version": SESSION_QUESTIONS.version,
                              "questions": SESSION_QUESTIONS.questions}, indent=1))
            return EXIT_OK
        return {"ask": cmd_ask, "session": cmd_session, "eval": cmd_eval, "doctor": cmd_doctor,
                "models": cmd_models}[args.command](args, post)
    except DecideError as exc:
        print(json.dumps(exc.envelope()), file=sys.stdout)
        return exc.exit_code
    except (OSError, ValueError) as exc:
        print(json.dumps(DecideError("usage", f"{type(exc).__name__}: {exc}", exit_code=EXIT_USAGE).envelope()))
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
