"""Project a tool's upstream JSON down to a result a caller can use inline (#828).

The problem this exists for: our search/chat tools returned the upstream JSON
essentially verbatim, and several vendors wrap a small answer in a large
envelope. Measured on five search/chat tools: a chat answer was 6% of its
response, message text 14–18% (rich-text and attachment copies 60–77%), search
snippets 22% (duplicate result copies 47%), and an issue search's own API plumbing
was 30%. Raw responses ran 38–117 KB.

At those sizes the MCP client refuses the result, spills it to a temp file and
hands the caller a "read this in chunks" instruction instead of the answer — so
every call cost a `python`/`jq` round-trip before it was usable.

This module holds only the vendor-neutral mechanics. The field maps live next to
the tools they belong to (each server's own `response_shaping.py`), because they
encode what one vendor's API means, not a shared rule.

## The contract `shape()` enforces

Shaping must never be able to cost a caller their answer, so every uncertain
case degrades to the full upstream payload rather than to a smaller wrong one:

* **`verbose=True` returns the raw bytes**, untouched. Every tool that shapes
  exposes that flag, so nothing is permanently hidden.
* **Error envelopes pass through.** `uc_proxy_client` signals failure as
  `{"ok": false, ...}` — `uc_oauth_reauthentication_required` carries a reauth
  URL, `rate_limited` a back-off. A shaper written for the success shape would
  strip exactly the fields that make those actionable.
* **An unrecognized payload passes through.** A shaper returns `None` when the
  response is not the shape it knows, so a changed upstream schema yields the
  whole payload instead of a confidently-empty projection. This is the important
  one: silently returning `{"results": []}` for a body we failed to parse would
  read as "no results" and be believed.
* **A shaper that raises fails open**, returning the raw payload with a visible
  `_shaping_error` key — a spilled-but-complete answer beats a lost one, and the
  key means the bug is still reported rather than swallowed.

Shaped responses always carry `_shaped`, so a caller can tell a projection ran
and how to get everything back. Shaping is applied unconditionally rather than
above a size threshold: a tool that returned one schema for large responses and
another for small ones would be unusable to write code against.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

# Marker added to every shaped response, and the note it carries. Kept short
# because it is paid on every call.
SHAPED_KEY = "_shaped"
SHAPED_NOTE = "projected for size; pass verbose=true for the raw upstream payload"

# Added instead when a shaper raised. The raw payload is returned alongside it.
SHAPING_ERROR_KEY = "_shaping_error"

# A shaper takes the parsed upstream body and returns the projection, or None to
# decline (the payload is not the shape it knows).
Shaper = Callable[[dict[str, Any]], "dict[str, Any] | None"]


def shape(raw: str, shaper: Shaper, *, verbose: bool = False) -> str:
    """Return `raw` projected through `shaper`, or `raw` itself when in doubt.

    `raw` is the JSON string a tool got back from `uc_proxy_client`; the return
    is the JSON string the tool hands its caller. See the module docstring for
    the passthrough cases — every one of them exists so shaping cannot lose an
    answer.
    """
    if verbose:
        return raw
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if not isinstance(data, dict):
        return raw
    if data.get("ok") is False:
        return raw
    try:
        shaped = shaper(data)
    except Exception as exc:  # noqa: BLE001 - fail open, visibly
        data[SHAPING_ERROR_KEY] = (
            f"{type(exc).__name__}: {exc}; returning the raw upstream payload"
        )
        return json.dumps(data, ensure_ascii=False)
    if shaped is None:
        return raw
    shaped[SHAPED_KEY] = SHAPED_NOTE
    return json.dumps(shaped, ensure_ascii=False)


def pick(
    mapping: Any,
    keys: Iterable[str],
    *,
    drop_none: bool = True,
) -> dict[str, Any]:
    """Whitelist-project a dict to `keys`, preserving the order given.

    `drop_none` omits keys whose value is None, which keeps a projection of a
    sparse upstream object from being mostly nulls. Pass False where the key's
    presence is itself the contract — a Jira `fields` list the caller asked for,
    say, where an absent key and a null one mean different things.

    A non-dict `mapping` yields `{}` rather than raising, so a shaper walking a
    list of heterogeneous objects does not need a type check per element.
    """
    if not isinstance(mapping, dict):
        return {}
    out: dict[str, Any] = {}
    for key in keys:
        if key not in mapping:
            continue
        value = mapping[key]
        if drop_none and value is None:
            continue
        out[key] = value
    return out


def drop_keys_deep(value: Any, keys: Iterable[str]) -> Any:
    """Recursively remove `keys` from every dict inside `value`.

    The blacklist counterpart to `pick`, for APIs whose bloat is a fixed set of
    self-describing keys repeated at every nesting level (Jira's `self`,
    `expand`, `iconUrl`, `avatarUrls`) rather than a wide object you want a few
    fields out of. Only ever use it for keys that carry no caller-visible
    meaning: a deep drop cannot tell `status.description` (boilerplate) from
    `fields.description` (the issue's body), so a key a caller might have asked
    for must not be in the set.
    """
    drop = frozenset(keys)
    return _drop_keys_deep(value, drop)


def _drop_keys_deep(value: Any, drop: frozenset[str]) -> Any:
    if isinstance(value, dict):
        return {
            k: _drop_keys_deep(v, drop) for k, v in value.items() if k not in drop
        }
    if isinstance(value, list):
        return [_drop_keys_deep(v, drop) for v in value]
    return value
