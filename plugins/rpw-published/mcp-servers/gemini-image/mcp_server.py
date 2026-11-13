"""
Gemini Image MCP Server — generate and edit images via Gemini native image generation.

Uses the google-genai SDK on the Vertex AI backend. Default model:
gemini-2.5-flash-image (GA). Friendly aliases (nano-banana / nano-banana-2 /
nano-banana-pro) map to real Vertex model IDs — see MODEL_ALIASES and the README
"Model selection" section.

Every response is parsed structurally and validated by magic bytes before any
file is written: a safety block, a text-only refusal, or an empty/non-image
response returns a structured, actionable error instead of persisting garbage
bytes to disk (issue #95).

Two backends, selected by ``GEMINI_IMAGE_BACKEND`` (#2563), both OAuth-derived
with no static API key:

- ``vertex`` (default): Vertex AI via gcloud Application Default Credentials
  (`gcloud auth application-default login`); the SDK mints + auto-refreshes
  short-lived access tokens at call time.
- ``databricks``: the Databricks-hosted Foundation Model API endpoints
  (``databricks-gemini-3-1-flash-image`` / ``databricks-gemini-3-pro-image``),
  authenticated with a Databricks CLI profile's OAuth tokens. No Google
  credential is involved; Databricks AI Gateway usage tracking applies.

Images are saved to disk and file paths are returned. A successful result is
the ``Image saved to: <path>`` line, followed — when the backend reported token
usage — by one ``Usage: {json}`` line carrying the backend, the requested and
resolved model, and the usage counters (``image_output_tokens`` among them), so
a caller can show cost per image (#2611).
"""

import base64
import json
import os
import sys
import tempfile
from pathlib import Path

from fastmcp import FastMCP
from google import genai
from google.genai import types

# Allow imports from the parent mcp-servers directory (shared lib/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.stale_auth import StaleAuthGuard, looks_like_stale_auth

DEFAULT_MODEL = "gemini-2.5-flash-image"
DEFAULT_VERTEX_LOCATION = "global"
OUTPUT_DIR = os.environ.get("GEMINI_IMAGE_OUTPUT_DIR", tempfile.gettempdir())

# Friendly aliases → real Vertex AI model IDs (issue #350). The raw IDs were
# verified live against `client.models.list()` on the Vertex backend; see the
# README "Model selection" section (and the discovery command there) for how to
# confirm which IDs your GCP project/region actually has access to. Passing a raw
# model id straight through still works — aliases are a convenience, not a gate.
MODEL_ALIASES = {
    "nano-banana": "gemini-2.5-flash-image",  # GA default
    "nano-banana-2": "gemini-3.1-flash-image",  # Nano Banana 2
    "nano-banana-pro": "gemini-3-pro-image",  # Nano Banana Pro
}

mcp = FastMCP(
    "gemini-image",
    instructions="Generate and edit images using Google Gemini native image generation",
)

# Process-local stale-auth latch (issue #195). Vertex AI mints short-lived tokens
# from gcloud ADC; once the ADC session is expired/revoked the SDK returns
# `401 UNAUTHENTICATED`, which this guard normalizes into an actionable envelope
# and short-circuits so we stop re-hitting Vertex on every tool call. The latch
# clears on process restart (run_mcp.py reloads env + ADC) or a code reset.
_STALE_AUTH = StaleAuthGuard(
    provider="vertex-ai",
    remediation=(
        "Re-authenticate gcloud Application Default Credentials: "
        "gcloud auth application-default login"
    ),
)


# --- Backend selection (#2563) ------------------------------------------------

BACKEND_ENV = "GEMINI_IMAGE_BACKEND"
DATABRICKS_PROFILE_ENV = "GEMINI_IMAGE_DATABRICKS_PROFILE"
_BACKENDS = ("vertex", "databricks")


def _backend() -> str:
    """The configured backend. An unknown value is an error, never a silent fallback."""
    value = (os.getenv(BACKEND_ENV) or "vertex").strip().lower()
    if value not in _BACKENDS:
        raise ValueError(f"{BACKEND_ENV}={value!r} is not one of {', '.join(_BACKENDS)}")
    return value


def _databricks_profile() -> str:
    """The Databricks CLI profile whose OAuth tokens authenticate the endpoint calls."""
    return (
        os.getenv(DATABRICKS_PROFILE_ENV)
        or os.getenv("DATABRICKS_CONFIG_PROFILE")
        or "DEFAULT"
    ).strip()


# Friendly aliases and raw Vertex ids -> Databricks pay-per-token endpoint names.
# Gemini 2.5 Flash Image is not hosted on Databricks, so the default model and the
# `nano-banana` alias resolve to its successor, 3.1 Flash Image — the default call
# must keep working when only the backend changes. Anything else passes through as
# a raw endpoint name (a custom or external-model endpoint).
DATABRICKS_ENDPOINTS = {
    "nano-banana": "databricks-gemini-3-1-flash-image",
    "gemini-2.5-flash-image": "databricks-gemini-3-1-flash-image",
    "nano-banana-2": "databricks-gemini-3-1-flash-image",
    "gemini-3.1-flash-image": "databricks-gemini-3-1-flash-image",
    "nano-banana-pro": "databricks-gemini-3-pro-image",
    "gemini-3-pro-image": "databricks-gemini-3-pro-image",
}


def _resolve_databricks_endpoint(model: str) -> str:
    return DATABRICKS_ENDPOINTS.get(model, model)


# --- Output size (#2611) -------------------------------------------------------

#: Values Gemini's ``image_config.image_size`` accepts. Gemini 3 image models honor
#: it (Pro returned a 2K render in the #2563 probes); Gemini 2.5 Flash Image does not.
IMAGE_SIZES = ("1K", "2K", "4K")


def _validate_image_size(image_size: str | None) -> str | None:
    """Normalize ``image_size``; ``None`` / empty means "model default, send nothing".

    An unknown value raises rather than being dropped: a silently ignored "4K" is a
    1K image the caller believes is 4K.
    """
    if image_size is None or not str(image_size).strip():
        return None
    value = str(image_size).strip().upper()
    if value not in IMAGE_SIZES:
        raise ValueError(f"image_size={image_size!r} is not one of {', '.join(IMAGE_SIZES)}")
    return value


def _invalid_image_size(image_size) -> str:
    return json.dumps(
        {
            "error": "invalid_image_size",
            "message": f"image_size={image_size!r} is not one of {', '.join(IMAGE_SIZES)}.",
            "next_action": "Pass 1K, 2K or 4K, or omit image_size for the model default.",
        },
        indent=2,
    )


# --- Usage reporting (#2611) ---------------------------------------------------

def _int_or_none(value):
    # bool is an int subclass; a MagicMock attribute is neither — both are rejected.
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _databricks_usage(response) -> dict:
    """The chat completion's ``usage`` block, numeric fields only.

    ``image_output_tokens`` is reported top-level on the Databricks endpoints
    (probed live on #2563); it is also looked up under ``completion_tokens_details``
    in case a later API revision nests it the OpenAI way.
    """
    raw = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(raw, dict):
        return {}
    usage = {k: v for k, v in raw.items() if _int_or_none(v) is not None}
    details = raw.get("completion_tokens_details")
    if isinstance(details, dict):
        nested = {k: v for k, v in details.items() if _int_or_none(v) is not None}
        if nested:
            usage["completion_tokens_details"] = nested
        if "image_output_tokens" not in usage and _int_or_none(details.get("image_tokens")) is not None:
            usage["image_output_tokens"] = details["image_tokens"]
    return usage


def _vertex_usage(response) -> dict:
    """Vertex ``usage_metadata`` as plain ints, with image tokens summed by modality."""
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return {}
    usage = {}
    for field in ("prompt_token_count", "candidates_token_count", "thoughts_token_count", "total_token_count"):
        value = _int_or_none(getattr(meta, field, None))
        if value is not None:
            usage[field] = value
    details = getattr(meta, "candidates_tokens_details", None)
    if isinstance(details, (list, tuple)):
        image_tokens = [
            _int_or_none(getattr(d, "token_count", None))
            for d in details
            if "IMAGE" in str(getattr(d, "modality", "")).upper()
        ]
        image_tokens = [t for t in image_tokens if t is not None]
        if image_tokens:
            usage["image_output_tokens"] = sum(image_tokens)
    return usage


def _success(prefix: str, path: str, *, backend: str, requested: str, resolved: str, usage: dict) -> str:
    """``<prefix>: <path>`` plus, when usage was reported, one ``Usage: {json}`` line.

    The first line is unchanged so existing callers that parse ``Image saved to:``
    keep working; the model fields make an alias resolution (e.g. the default model
    landing on 3.1 Flash Image on Databricks) visible instead of silent.
    """
    line = f"{prefix}: {path}"
    if not usage:
        return line
    payload = {"backend": backend, "requested_model": requested, "resolved_model": resolved, **usage}
    return f"{line}\nUsage: {json.dumps(payload, sort_keys=True)}"


def _get_client() -> genai.Client:
    """Build a Vertex AI Gemini client authenticated with gcloud ADC.

    Reads GOOGLE_CLOUD_PROJECT (required) and GOOGLE_CLOUD_LOCATION (defaults to
    global). The SDK obtains and refreshes access tokens from Application
    Default Credentials.
    """
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise RuntimeError(
            "GOOGLE_CLOUD_PROJECT not set — required for Vertex AI (gcloud ADC)"
        )
    location = os.getenv("GOOGLE_CLOUD_LOCATION", DEFAULT_VERTEX_LOCATION)
    return genai.Client(vertexai=True, project=project, location=location)


_STALE_AUTH_DATABRICKS = StaleAuthGuard(
    provider="databricks",
    remediation="Re-authenticate the Databricks profile: databricks auth login --profile <profile>",
)


def _stale_guard() -> StaleAuthGuard:
    """The stale-auth latch for the active backend, remediation naming the real profile."""
    if _backend() == "databricks":
        _STALE_AUTH_DATABRICKS.remediation = (
            "Re-authenticate the Databricks profile: "
            f"databricks auth login --profile {_databricks_profile()}"
        )
        return _STALE_AUTH_DATABRICKS
    return _STALE_AUTH


def _databricks_invoke(endpoint: str, body: dict) -> dict:
    """POST one chat request to a Databricks serving endpoint; the only network seam.

    The SDK's ``api_client`` resolves the profile's OAuth token from the CLI cache
    and refreshes it, so no credential is read or stored here. Patched in tests.
    """
    from databricks.sdk import WorkspaceClient

    client = WorkspaceClient(profile=_databricks_profile())
    return client.api_client.do("POST", f"/serving-endpoints/{endpoint}/invocations", body=body)


def _data_url_bytes(url: str) -> bytes | None:
    """Decode a ``data:<mime>;base64,<payload>`` URL; ``None`` for anything else."""
    if not isinstance(url, str) or not url.startswith("data:") or "," not in url:
        return None
    try:
        return base64.b64decode(url.split(",", 1)[1])
    except (ValueError, TypeError):
        return None


def _extract_databricks_image(response: dict, endpoint: str):
    """Locate the image in a Databricks chat completion.

    ``content`` is a list of parts; images arrive as ``image_url`` data URLs.
    **The last valid image wins**: Gemini 3 Pro Image streams a draft image, more
    reasoning, then the final render (probed live, #2563). A blocked prompt comes
    back as an empty text part with ``finish_reason: "error"``. Returns
    ``(bytes, None)`` or ``(None, error_json)``, mirroring
    :func:`_extract_image_bytes`.
    """
    choices = (response.get("choices") or []) if isinstance(response, dict) else []
    choice = choices[0] if choices else {}
    content = (choice.get("message") or {}).get("content")
    parts = content if isinstance(content, list) else [{"type": "text", "text": content or ""}]
    found, saw_image, texts = None, False, []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "image_url":
            saw_image = True
            data = _data_url_bytes((part.get("image_url") or {}).get("url"))
            if data and _looks_like_image(data):
                found = data
        elif part.get("type") == "text" and part.get("text"):
            texts.append(part["text"])
    if found is not None:
        return found, None
    envelope = {
        "error": "no_image_in_response",
        "message": (
            "Gemini returned no valid image"
            + (" — the image part was not a valid PNG/JPEG" if saw_image else " — the response carried no image part")
            + " (safety block, text-only refusal, or empty response). No file was written."
        ),
        "model": endpoint,
        "backend": "databricks",
        "next_action": "Rephrase the prompt/instruction, or try a different model (see README 'Model selection').",
    }
    if texts:
        envelope["model_text"] = "\n".join(texts).strip()
    if choice.get("finish_reason") is not None:
        envelope["finish_reason"] = str(choice["finish_reason"])
    return None, json.dumps(envelope, indent=2)


def _databricks_model_error(requested: str, endpoint: str, detail: str) -> str:
    return json.dumps(
        {
            "error": "invalid_model",
            "message": f"Databricks has no serving endpoint '{endpoint}' on profile '{_databricks_profile()}'.",
            "requested_model": requested,
            "resolved_model": endpoint,
            "known_aliases": DATABRICKS_ENDPOINTS,
            "next_action": (
                "Use a known alias, or check the workspace serves the endpoint "
                "(`databricks serving-endpoints get <name>`). The Gemini image endpoints "
                "are global and need cross-Geo processing enabled on the workspace "
                "(account console > workspace > Security and compliance)."
            ),
            "detail": detail,
        },
        indent=2,
    )


def _databricks_generate(content, model: str, image_config: dict | None):
    """Run one request on the Databricks backend; ``(bytes, usage, None)`` or ``(None, {}, error)``."""
    endpoint = _resolve_databricks_endpoint(model)
    body: dict = {"messages": [{"role": "user", "content": content}]}
    if image_config:
        # Top-level unknown fields are forwarded into Gemini's generation_config;
        # `extra_body` is not (400). Probed live on #2563.
        body["image_config"] = image_config
    try:
        response = _databricks_invoke(endpoint, body)
    except Exception as e:
        # Stale auth propagates to the tool's guard; a missing endpoint gets its own envelope.
        if not looks_like_stale_auth(str(e)) and _looks_like_model_error(str(e), endpoint):
            return None, {}, _databricks_model_error(model, endpoint, str(e))
        raise
    image, err = _extract_databricks_image(response, endpoint)
    return image, _databricks_usage(response), err


def _save_image(image_data: bytes, filename: str) -> str:
    """Save image bytes to OUTPUT_DIR and return the full path."""
    # Strip directory components to prevent path traversal
    filename = Path(filename).name
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_bytes(image_data)
    return str(path)


def _resolve_model(model: str) -> str:
    """Map a friendly alias to a real Vertex model id; pass raw ids through (#350)."""
    return MODEL_ALIASES.get(model, model)


def _looks_like_image(data: bytes) -> bool:
    """True if ``data`` starts with a known image magic-byte signature.

    Guards issue #95: Gemini can return a text-only refusal, an empty
    inline-data block, or safety-filter bytes that are NOT a real image. We only
    ever write bytes to disk that carry a genuine PNG/JPEG (also GIF/WEBP) header.
    """
    if not data or len(data) < 12:
        return False
    if data[:8] == b"\x89PNG\r\n\x1a\n":  # PNG
        return True
    if data[:3] == b"\xff\xd8\xff":  # JPEG
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):  # GIF
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WEBP
        return True
    return False


def _response_metadata(response) -> dict:
    """Pull actionable diagnostics (block/finish reason, safety ratings) from a response.

    Returned dict is merged into the structured no-image error so the caller can
    see *why* Gemini declined — safety block, recitation, empty candidate, etc.
    """
    meta: dict = {}
    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason is not None:
            meta["block_reason"] = str(block_reason)
        block_msg = getattr(prompt_feedback, "block_reason_message", None)
        if block_msg:
            meta["block_reason_message"] = block_msg

    candidates = getattr(response, "candidates", None) or []
    if candidates:
        candidate = candidates[0]
        finish_reason = getattr(candidate, "finish_reason", None)
        if finish_reason is not None:
            meta["finish_reason"] = str(finish_reason)
        finish_msg = getattr(candidate, "finish_message", None)
        if finish_msg:
            meta["finish_message"] = finish_msg
        ratings = getattr(candidate, "safety_ratings", None)
        blocked = [
            {
                "category": str(getattr(r, "category", "")),
                "probability": str(getattr(r, "probability", "")),
            }
            for r in ratings
            if getattr(r, "blocked", False)
        ] if isinstance(ratings, (list, tuple)) else []
        if blocked:
            meta["blocked_safety_ratings"] = blocked
    return meta


def _collect_text(response) -> str:
    """Join any text parts the model returned (its explanation/refusal), if present.

    A part's ``text`` is a ``str`` or ``None`` in real responses; anything else is
    ignored so a malformed/partial response can't crash the error path.
    """
    texts = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            text = getattr(part, "text", None)
            if isinstance(text, str) and text:
                texts.append(text)
    return "\n".join(texts).strip()


def _no_image_error(response, model: str, saw_inline: bool) -> str:
    """Build the structured, actionable no-image error envelope (issue #95).

    Never written to disk — returned to the caller so it knows what happened
    (safety block / refusal / empty response), the text the model returned, and
    the response metadata (finish_reason, block_reason, blocked safety ratings).
    """
    if saw_inline:
        message = (
            "Gemini returned no valid image — the inline bytes were not a valid "
            "PNG/JPEG, usually a safety filter or model refusal. No file was written."
        )
    else:
        message = (
            "Gemini returned no valid image — the response carried no image part "
            "(safety block, text-only refusal, or empty candidate). No file was written."
        )
    envelope = {
        "error": "no_image_in_response",
        "message": message,
        "model": model,
        "next_action": (
            "Rephrase the prompt/instruction, or try a different model "
            "(see README 'Model selection')."
        ),
    }
    model_text = _collect_text(response)
    if model_text:
        envelope["model_text"] = model_text
    envelope.update(_response_metadata(response))
    return json.dumps(envelope, indent=2)


def _extract_image_bytes(response, model: str):
    """Structurally locate a valid image in a Gemini response.

    Returns ``(image_bytes, None)`` when a part carries genuine PNG/JPEG bytes,
    or ``(None, error_json)`` with a structured actionable error otherwise
    (issue #95 — no image, safety block, or non-image bytes). Decodes inline
    data whether the SDK hands back raw bytes or a base64 string.
    """
    saw_inline = False
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            raw = getattr(inline, "data", None) if inline is not None else None
            if not raw:
                continue
            saw_inline = True
            data = raw if isinstance(raw, bytes) else base64.b64decode(raw)
            if _looks_like_image(data):
                return data, None
    return None, _no_image_error(response, model, saw_inline)


# Signatures Vertex AI emits when a model id is unknown or the project/region has
# no access to it — used to turn a raw SDK exception into an actionable envelope
# that also surfaces the known aliases (issue #350).
_MODEL_ERROR_MARKERS = (
    "not found",
    "was not found",
    "does not exist",
    "not supported",
    "is not available",
    "not allowed to use",
    "404",
)


def _looks_like_model_error(text: str, resolved_model: str) -> bool:
    """True if ``text`` reads like Vertex rejecting the (resolved) model id."""
    if not text:
        return False
    lower = text.lower()
    if resolved_model and resolved_model.lower() in lower:
        return True
    return any(marker in lower for marker in _MODEL_ERROR_MARKERS)


def _model_error(requested_model: str, resolved_model: str, detail: str) -> str:
    """Structured error for an unknown/unavailable model, with the alias list (#350)."""
    envelope = {
        "error": "invalid_model",
        "message": (
            f"Vertex AI rejected model '{resolved_model}'. It may not exist, or your "
            "GCP project/region may not have access to it yet."
        ),
        "requested_model": requested_model,
        "resolved_model": resolved_model,
        "known_aliases": MODEL_ALIASES,
        "next_action": (
            "Use one of 'known_aliases' or a valid raw Vertex model id. Discover "
            "what your project can access with: gcloud ai models list "
            "--region=<location>  (or google-genai client.models.list())."
        ),
        "detail": detail,
    }
    return json.dumps(envelope, indent=2)


@mcp.tool()
def generate_image(
    prompt: str,
    filename: str = "generated.png",
    aspect_ratio: str = "1:1",
    model: str = DEFAULT_MODEL,
    image_size: str | None = None,
) -> str:
    """Generate an image from a text prompt using Gemini native image generation.

    Args:
        prompt: Text description of the image to generate.
        filename: Output filename (saved to temp dir). Default: generated.png
        aspect_ratio: Aspect ratio — 1:1, 3:4, 4:3, 9:16, 16:9. Default: 1:1
        model: Gemini model or alias to use. Aliases: nano-banana,
            nano-banana-2, nano-banana-pro. Default: gemini-2.5-flash-image
        image_size: Output resolution — 1K, 2K or 4K. Omit for the model default.
            Honored by Gemini 3 image models (nano-banana-2, nano-banana-pro);
            Gemini 2.5 Flash Image does not support it.

    On success returns ``Image saved to: <path>``, followed by a ``Usage: {json}``
    line (token counts incl. ``image_output_tokens``) when the backend reports usage.
    """
    # Short-circuit if a prior call already found the credential stale — return the
    # actionable re-auth envelope without re-hitting Vertex AI (issue #195).
    guard = _stale_guard()
    stale = guard.short_circuit()
    if stale is not None:
        return stale.as_message()
    resolved_model = _resolve_model(model)
    try:
        size = _validate_image_size(image_size)
    except ValueError:
        return _invalid_image_size(image_size)
    try:
        if _backend() == "databricks":
            image_config = {"aspect_ratio": aspect_ratio}
            if size:
                image_config["image_size"] = size
            image_bytes, usage, err = _databricks_generate(prompt, model, image_config)
            if err is not None:
                return err
            return _success(
                "Image saved to", _save_image(image_bytes, filename), backend="databricks",
                requested=model, resolved=_resolve_databricks_endpoint(model), usage=usage,
            )
        client = _get_client()
        image_config = (
            types.ImageConfig(aspect_ratio=aspect_ratio, image_size=size)
            if size
            else types.ImageConfig(aspect_ratio=aspect_ratio)
        )
        response = client.models.generate_content(
            model=resolved_model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=image_config,
            ),
        )

        # Parse structurally + validate magic bytes before writing (issue #95):
        # never persist a safety-block/refusal/non-image response to disk.
        image_bytes, err = _extract_image_bytes(response, resolved_model)
        if err is not None:
            return err
        path = _save_image(image_bytes, filename)
        return _success(
            "Image saved to", path, backend="vertex",
            requested=model, resolved=resolved_model, usage=_vertex_usage(response),
        )
    except Exception as e:
        # Normalize stale/expired-credential failures into the shared actionable
        # envelope and latch the guard so subsequent calls short-circuit.
        stale = guard.classify(e)
        if stale is not None:
            return stale.as_message()
        # Surface unknown/unavailable-model rejections with the alias list (#350).
        if _looks_like_model_error(str(e), resolved_model):
            return _model_error(model, resolved_model, str(e))
        return f"Error generating image: {e}"


@mcp.tool()
def edit_image(
    image_path: str,
    instruction: str,
    filename: str = "edited.png",
    model: str = DEFAULT_MODEL,
) -> str:
    """Edit an existing image using a text instruction via Gemini native image generation.

    Args:
        image_path: Path to the source image file to edit.
        instruction: Text instruction describing the edit (e.g., "make the sky sunset orange").
        filename: Output filename for the edited image. Default: edited.png
        model: Gemini model or alias to use. Aliases: nano-banana,
            nano-banana-2, nano-banana-pro. Default: gemini-2.5-flash-image
    """
    # Short-circuit a known-stale credential before doing any work (issue #195).
    guard = _stale_guard()
    stale = guard.short_circuit()
    if stale is not None:
        return stale.as_message()
    resolved_model = _resolve_model(model)
    try:
        source_path = Path(image_path)
        if not source_path.exists():
            return f"Error: Source image not found at {image_path}"

        image_bytes = source_path.read_bytes()
        mime_type = "image/png"
        if source_path.suffix.lower() in (".jpg", ".jpeg"):
            mime_type = "image/jpeg"
        elif source_path.suffix.lower() == ".webp":
            mime_type = "image/webp"

        if _backend() == "databricks":
            data_url = f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode()
            content = [
                {"type": "text", "text": instruction},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
            edited_bytes, usage, err = _databricks_generate(content, model, None)
            if err is not None:
                return err
            return _success(
                "Edited image saved to", _save_image(edited_bytes, filename), backend="databricks",
                requested=model, resolved=_resolve_databricks_endpoint(model), usage=usage,
            )
        client = _get_client()
        response = client.models.generate_content(
            model=resolved_model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                instruction,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        # Parse structurally + validate magic bytes before writing (issue #95):
        # a safety-blocked / refused / text-only edit must NOT hit disk.
        edited_bytes, err = _extract_image_bytes(response, resolved_model)
        if err is not None:
            return err
        path = _save_image(edited_bytes, filename)
        return _success(
            "Edited image saved to", path, backend="vertex",
            requested=model, resolved=resolved_model, usage=_vertex_usage(response),
        )
    except Exception as e:
        stale = guard.classify(e)
        if stale is not None:
            return stale.as_message()
        # Surface unknown/unavailable-model rejections with the alias list (#350).
        if _looks_like_model_error(str(e), resolved_model):
            return _model_error(model, resolved_model, str(e))
        return f"Error editing image: {e}"


def main() -> None:
    """Run the gemini-image MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
