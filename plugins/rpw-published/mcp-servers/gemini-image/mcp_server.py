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

Authentication is OAuth-derived: gcloud Application Default Credentials
(`gcloud auth application-default login`) provide the identity, and the SDK
mints + auto-refreshes short-lived Vertex AI access tokens at call time. No
static API key is used.

Images are saved to disk and file paths are returned.
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

from lib.stale_auth import StaleAuthGuard

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
) -> str:
    """Generate an image from a text prompt using Gemini native image generation.

    Args:
        prompt: Text description of the image to generate.
        filename: Output filename (saved to temp dir). Default: generated.png
        aspect_ratio: Aspect ratio — 1:1, 3:4, 4:3, 9:16, 16:9. Default: 1:1
        model: Gemini model or alias to use. Aliases: nano-banana,
            nano-banana-2, nano-banana-pro. Default: gemini-2.5-flash-image
    """
    # Short-circuit if a prior call already found the credential stale — return the
    # actionable re-auth envelope without re-hitting Vertex AI (issue #195).
    stale = _STALE_AUTH.short_circuit()
    if stale is not None:
        return stale.as_message()
    resolved_model = _resolve_model(model)
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=resolved_model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )

        # Parse structurally + validate magic bytes before writing (issue #95):
        # never persist a safety-block/refusal/non-image response to disk.
        image_bytes, err = _extract_image_bytes(response, resolved_model)
        if err is not None:
            return err
        path = _save_image(image_bytes, filename)
        return f"Image saved to: {path}"
    except Exception as e:
        # Normalize stale/expired-credential failures into the shared actionable
        # envelope and latch the guard so subsequent calls short-circuit.
        stale = _STALE_AUTH.classify(e)
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
    stale = _STALE_AUTH.short_circuit()
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
        return f"Edited image saved to: {path}"
    except Exception as e:
        stale = _STALE_AUTH.classify(e)
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
