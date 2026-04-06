# Gemini Image Gen + Exa Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Gemini native image generation and Exa semantic/code search MCP tools to rpw-building plugin.

**Architecture:** Convert rpw-building from single-server MCP config to aggregated `.mcp.json` (like rpw-working). Add a custom Gemini image gen MCP server and Exa's hosted MCP endpoint. Gemini server follows established patterns: FastMCP, env_loader, run_mcp.py entry point.

**Tech Stack:** `google-genai` SDK, `fastmcp>=3.0.0`, `python-dotenv>=1.2.1`, Exa hosted MCP

---

### Task 1: Create aggregated .mcp.json and update plugin.json

**Files:**
- Create: `plugins/rpw-building/.mcp.json`
- Modify: `plugins/rpw-building/.claude-plugin/plugin.json`

**Step 1: Create the aggregated .mcp.json**

```json
{
  "_comment": "Aggregated MCP config for rpw-building. Includes local servers and hosted endpoints.",
  "mcpServers": {
    "cmux": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "${CLAUDE_PLUGIN_ROOT}/mcp-servers/cmux",
        "python",
        "${CLAUDE_PLUGIN_ROOT}/mcp-servers/cmux/run_mcp.py"
      ]
    },
    "gemini-image": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "${CLAUDE_PLUGIN_ROOT}/mcp-servers/gemini-image",
        "python",
        "${CLAUDE_PLUGIN_ROOT}/mcp-servers/gemini-image/run_mcp.py"
      ]
    },
    "exa": {
      "url": "https://mcp.exa.ai/mcp?tools=web_search_advanced_exa,code_search_exa"
    }
  }
}
```

**Step 2: Update plugin.json mcpServers pointer**

Change `"mcpServers": "./mcp-servers/cmux/cmux.mcp.json"` to `"mcpServers": "./.mcp.json"`.

**Step 3: Run repo validation tests**

Run: `uv run python -m unittest tests.test_repo_validations -v`
Expected: All tests pass. The test `test_rpw_building_mcp_servers_follow_standards` validates both file and directory formats. The test `test_mcp_servers_json_file_has_valid_structure` ensures the file has a `mcpServers` key.

**Step 4: Commit**

```bash
git add plugins/rpw-building/.mcp.json plugins/rpw-building/.claude-plugin/plugin.json
git commit -m "refactor: convert rpw-building to aggregated .mcp.json with cmux, gemini-image, exa"
```

---

### Task 2: Create env_loader lib for rpw-building

**Files:**
- Create: `plugins/rpw-building/mcp-servers/lib/__init__.py`
- Create: `plugins/rpw-building/mcp-servers/lib/env_loader.py`

**Step 1: Create lib directory with env_loader**

Copy the env_loader pattern from rpw-working. The file provides:
- `load_selected_env(base_dir)` — reads `dev.env`/`test.env`/`prod.env` based on `APP_ENV`
- `validate_required_env(list)` — checks required env vars exist

```python
# plugins/rpw-building/mcp-servers/lib/__init__.py
# (empty)
```

```python
# plugins/rpw-building/mcp-servers/lib/env_loader.py
"""
Shared env-loading logic for MCP server wrappers.

Provides APP_ENV selection (dev/test/prod), env file resolution,
dotenv loading, and required-variable validation.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

VALID_APP_ENVS = {"dev", "test", "prod"}


def get_app_env() -> str:
    app_env = os.getenv("APP_ENV", "dev").strip().lower()
    if app_env not in VALID_APP_ENVS:
        raise ValueError(
            f"Invalid APP_ENV '{app_env}'. Expected one of: {sorted(VALID_APP_ENVS)}"
        )
    return app_env


def resolve_env_path(base_dir: Path, app_env: str) -> Path:
    return base_dir / f"{app_env}.env"


def load_selected_env(base_dir: Path) -> tuple[str, Path]:
    app_env = get_app_env()
    env_path = resolve_env_path(base_dir, app_env)
    if not env_path.exists():
        raise FileNotFoundError(
            f"Env file not found at {env_path}. Copy template.env to {app_env}.env first."
        )
    load_dotenv(env_path)
    return app_env, env_path


def validate_required_env(required: list[str]) -> list[str]:
    return [v for v in required if not os.getenv(v)]
```

**Step 2: Commit**

```bash
git add plugins/rpw-building/mcp-servers/lib/
git commit -m "feat: add env_loader lib for rpw-building MCP servers"
```

---

### Task 3: Create gemini-image MCP server scaffolding

**Files:**
- Create: `plugins/rpw-building/mcp-servers/gemini-image/pyproject.toml`
- Create: `plugins/rpw-building/mcp-servers/gemini-image/template.env`
- Create: `plugins/rpw-building/mcp-servers/gemini-image/run_mcp.py`
- Create: `plugins/rpw-building/mcp-servers/gemini-image/README.md`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "gemini-image"
version = "0.1.0"
description = "MCP server for Gemini native image generation and editing"
readme = "README.md"
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=3.0.0",
    "google-genai>=1.0.0",
    "python-dotenv>=1.2.1",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0"]
```

**Step 2: Create template.env**

```
# Copy this file to dev.env, test.env, or prod.env and fill values.
# Select at runtime with APP_ENV=dev|test|prod.
GEMINI_API_KEY=your_gemini_api_key_here
```

**Step 3: Create run_mcp.py**

```python
"""
Thin wrapper that loads APP_ENV-selected env files and runs the Gemini Image MCP server.
Keeps MCP config JSON secret-free.

Usage:
    APP_ENV=dev uv run python run_mcp.py
    uv run python run_mcp.py
"""

import sys
from pathlib import Path

# Allow imports from the parent mcp-servers directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.env_loader import load_selected_env, validate_required_env

REQUIRED = ["GEMINI_API_KEY"]


def main() -> None:
    base_dir = Path(__file__).parent
    try:
        app_env, env_path = load_selected_env(base_dir)
    except (ValueError, FileNotFoundError) as exc:
        print(f"\u274c {exc}", file=sys.stderr)
        sys.exit(1)

    missing = validate_required_env(REQUIRED)
    if missing:
        print(
            f"\u274c Missing env vars in {env_path.name} for APP_ENV={app_env}: {missing}",
            file=sys.stderr,
        )
        sys.exit(1)

    from mcp_server import main as server_main

    server_main()


if __name__ == "__main__":
    main()
```

**Step 4: Create README.md**

```markdown
# gemini-image MCP Server

Provides image generation and editing tools via Google's Gemini native image generation API.

## Setup

1. Get a Gemini API key from https://aistudio.google.com/apikey
2. Copy `template.env` to `dev.env` and fill in your key
3. The server is auto-started by the rpw-building plugin

## Tools

- `generate_image` — Generate an image from a text prompt
- `edit_image` — Edit an existing image with a text instruction

## Manual Testing

```bash
APP_ENV=dev uv run python run_mcp.py
```
```

**Step 5: Commit**

```bash
git add plugins/rpw-building/mcp-servers/gemini-image/
git commit -m "feat: scaffold gemini-image MCP server with env, pyproject, run_mcp"
```

---

### Task 4: Implement gemini-image mcp_server.py

**Files:**
- Create: `plugins/rpw-building/mcp-servers/gemini-image/mcp_server.py`

**Step 1: Write the failing test**

Create: `plugins/rpw-building/mcp-servers/gemini-image/test_run_mcp_env.py`

```python
import unittest
from unittest.mock import patch

import run_mcp


class TestGeminiImageRunMcpRequired(unittest.TestCase):
    """Server-specific tests: validate the REQUIRED list for gemini-image."""

    def test_required_contains_expected_vars(self):
        self.assertEqual(run_mcp.REQUIRED, ["GEMINI_API_KEY"])

    def test_validate_required_env_detects_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, ["GEMINI_API_KEY"])

    def test_validate_required_env_passes_when_set(self):
        env = {"GEMINI_API_KEY": "test-key"}
        with patch.dict("os.environ", env, clear=True):
            from lib.env_loader import validate_required_env

            missing = validate_required_env(run_mcp.REQUIRED)
            self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
```

**Step 2: Run test to verify it passes (scaffolding already in place)**

Run: `cd plugins/rpw-building/mcp-servers/gemini-image && uv run python -m pytest test_run_mcp_env.py -v`
Expected: 3 tests PASS

**Step 3: Write mcp_server.py**

```python
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
    description="Generate and edit images using Google Gemini native image generation",
)


def _get_client() -> genai.Client:
    """Build Gemini client using GEMINI_API_KEY from environment."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


def _save_image(image_data: bytes, filename: str) -> str:
    """Save image bytes to OUTPUT_DIR and return the full path."""
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
                image_bytes = base64.b64decode(part.inline_data.data)
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
```

**Step 4: Run repo validation tests**

Run: `uv run python -m unittest tests.test_repo_validations -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add plugins/rpw-building/mcp-servers/gemini-image/mcp_server.py plugins/rpw-building/mcp-servers/gemini-image/test_run_mcp_env.py
git commit -m "feat: implement gemini-image MCP server with generate and edit tools"
```

---

### Task 5: Update repo validation tests for new MCP servers

**Files:**
- Modify: `tests/test_repo_validations.py`

**Step 1: Add test for rpw-building MCP servers**

Add a test alongside `test_working_plugin_has_mcp_servers` that validates the gemini-image server has required files:

```python
def test_building_plugin_has_mcp_servers(self):
    root = _repo_root()
    plugin_root = os.path.join(root, "plugins", "rpw-building")
    self.assertTrue(os.path.isfile(os.path.join(plugin_root, ".mcp.json")))
    for server in ["gemini-image"]:
        server_root = os.path.join(plugin_root, "mcp-servers", server)
        for required in ["pyproject.toml", "run_mcp.py", "mcp_server.py", "README.md"]:
            self.assertTrue(
                os.path.isfile(os.path.join(server_root, required)),
                f"missing {required} for {server}",
            )
```

Note: Don't add cmux to this list — it doesn't have a README.md and predates this standard.

**Step 2: Update `_mcp_json_paths` to also check rpw-building**

The existing `_mcp_json_paths` function only checks rpw-working. Update it to check all plugins that declare mcpServers, or add rpw-building explicitly.

```python
def _mcp_json_paths(root):
    """Return paths to .mcp.json and .reference.json files under plugins with MCP servers."""
    paths = []
    for plugin_name in ["rpw-working", "rpw-building"]:
        plugin_root = os.path.join(root, "plugins", plugin_name)
        top_mcp = os.path.join(plugin_root, ".mcp.json")
        if os.path.isfile(top_mcp):
            paths.append(top_mcp)
        mcp_dir = os.path.join(plugin_root, "mcp-servers")
        if not os.path.isdir(mcp_dir):
            continue
        for name in os.listdir(mcp_dir):
            subdir = os.path.join(mcp_dir, name)
            if not os.path.isdir(subdir):
                continue
            for f in os.listdir(subdir):
                if f.endswith(".mcp.json") or f.endswith(".reference.json"):
                    paths.append(os.path.join(subdir, f))
    return paths
```

**Step 3: Also update `test_rpw_working_manifest_declares_mcp_servers_to_mcp_json` — add a parallel one for rpw-building**

```python
def test_rpw_building_manifest_declares_mcp_servers_to_mcp_json(self):
    root = _repo_root()
    manifest_path = os.path.join(root, "plugins", "rpw-building", ".claude-plugin", "plugin.json")
    with open(manifest_path) as f:
        manifest = json.load(f)
    self.assertIn("mcpServers", manifest, "rpw-building must declare mcpServers")
    self.assertEqual(
        manifest.get("mcpServers"),
        "./.mcp.json",
        "rpw-building mcpServers must point to ./.mcp.json",
    )
```

**Step 4: Run all validation tests**

Run: `uv run python -m unittest tests.test_repo_validations -v`
Expected: All tests pass including new ones

**Step 5: Commit**

```bash
git add tests/test_repo_validations.py
git commit -m "test: add repo validations for rpw-building MCP servers and aggregated config"
```

---

### Task 6: Create dev.env and verify end-to-end

**Files:**
- Create: `plugins/rpw-building/mcp-servers/gemini-image/dev.env` (gitignored, not committed)

**Step 1: Verify .gitignore covers env files**

Check that `*.env` or `dev.env` patterns are in .gitignore. If not, add them.

**Step 2: Create dev.env with actual API key**

```
GEMINI_API_KEY=<actual key — ask user>
```

**Step 3: Test the MCP server starts**

Run: `cd plugins/rpw-building/mcp-servers/gemini-image && APP_ENV=dev uv run python -c "from mcp_server import mcp; print('Server loads OK')"`
Expected: "Server loads OK" (validates imports resolve)

**Step 4: Run full validation suite**

Run: `uv run python -m unittest tests.test_repo_validations -v`
Expected: All pass

**Step 5: Final commit (if any gitignore changes needed)**

```bash
git add .gitignore
git commit -m "chore: ensure env files are gitignored for rpw-building MCP servers"
```
