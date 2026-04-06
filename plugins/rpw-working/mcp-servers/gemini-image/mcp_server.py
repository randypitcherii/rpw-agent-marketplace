"""
Gemini Image MCP Server — generate and edit images via Gemini native image generation.

Uses the google-genai SDK with the Gemini API. Default model: gemini-2.5-flash-image (GA).
Images are saved to disk and file paths are returned.
"""

import base64
import os
import tempfile
from pathlib import Path

from fastmcp import FastMCP
from google import genai
from google.genai import types

DEFAULT_MODEL = "gemini-2.5-flash-image"
OUTPUT_DIR = os.environ.get("GEMINI_IMAGE_OUTPUT_DIR", tempfile.gettempdir())

mcp = FastMCP(
    "gemini-image",
    instructions="Generate and edit images using Google Gemini native image generation",
)


def _get_client() -> genai.Client:
    """Build Gemini client using GEMINI_API_KEY from environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


def _save_image(image_data: bytes, filename: str) -> str:
    """Save image bytes to OUTPUT_DIR and return the full path."""
    # Strip directory components to prevent path traversal
    filename = Path(filename).name
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_bytes(image_data)
    return str(path)


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
        model: Gemini model to use. Default: gemini-2.5-flash-image
    """
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
            ),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                raw = part.inline_data.data
                image_bytes = raw if isinstance(raw, bytes) else base64.b64decode(raw)
                path = _save_image(image_bytes, filename)
                return f"Image saved to: {path}"

        return "Error: No image was generated. The model may have refused the prompt."
    except Exception as e:
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
        model: Gemini model to use. Default: gemini-2.5-flash-image
    """
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
            model=model,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                instruction,
            ],
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                edited_bytes = base64.b64decode(part.inline_data.data)
                path = _save_image(edited_bytes, filename)
                return f"Edited image saved to: {path}"

        return "Error: No edited image was generated. The model may have refused the edit."
    except Exception as e:
        return f"Error editing image: {e}"


def main() -> None:
    """Run the gemini-image MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
