---
name: raycast-extension-development
description: Use when building Raycast extensions, especially with Python/uv dependencies, encountering venv corruption, authentication issues, or path race conditions - provides critical patterns from production fixes including .gitignore, lazy initialization, and validation
---

# Raycast Extension Development

## Overview

Building Raycast extensions requires specific patterns to avoid corruption, race conditions, and authentication bugs. Official docs at https://developers.raycast.com.

**Core principle:** Raycast copies your entire assets directory, including hidden files. This breaks Python venvs with absolute path symlinks.

## When to Use

**Use when:**
- Building any Raycast extension
- Using Python scripts in assets directory
- Managing dependencies with uv
- Handling authentication or validation
- Encountering "venv corruption" or "module not found" errors
- Path-related race conditions or timing issues

**Critical symptoms this fixes:**
- Python imports fail after Raycast copies assets
- Race conditions with path initialization
- Authentication overrides from profile settings
- Missing validation for multimodal message formats

## Reference Official Docs FIRST

**ALWAYS check https://developers.raycast.com before implementing:**
- API reference for @raycast/api components
- Extension guidelines and best practices
- TypeScript/React patterns
- Command structure and lifecycle

Use WebFetch to get current documentation when needed.

## Critical Pattern: Python + uv in Assets

**Problem:** Raycast copies assets directory including .venv. Absolute path symlinks break.

**Solution (4-step fix):**

### 1. ALWAYS Add .gitignore

```gitignore
# In your-extension/.gitignore
assets/python/.venv/
```

**Why:** Exclude .venv from source so Raycast doesn't copy it. uv will create fresh venv at runtime.

### 2. ALWAYS Use Lazy Initialization for Paths

```typescript
// ❌ BAD: Race condition
const proxyPath = getProxyPath();

// ✅ GOOD: Lazy init with useState
const [proxyPath] = useState(() => getProxyPath());
```

**Why:** Prevents race condition where path accessed before initialization completes.

### 3. ALWAYS cd to Working Directory in Wrapper Scripts

```bash
#!/bin/bash
cd "${proxyPath}"  # Set working directory FIRST
export PATH="${uvPath}:${PATH}"

# Sync venv to ensure dependencies installed fresh
"${uvPath}" sync --quiet 2>/dev/null || true

# Now run the script
exec "${uvPath}" run python "${script}"
```

**Why:** Ensures uv sync and uv run execute in correct directory with access to pyproject.toml.

### 4. ALWAYS Run uv sync Before uv run

**Why:** With .venv excluded from source, must recreate it at runtime. uv sync installs dependencies from pyproject.toml.

## Authentication Patterns

### Don't Pass Profile to Config When Setting auth_type

```python
# ❌ BAD: Profile settings override auth_type
config = Config(
    host=workspace_url,
    profile=profile,
    auth_type="external-browser",  # Gets overridden!
)

# ✅ GOOD: Only set host and auth_type
config = Config(
    host=workspace_url,
    auth_type="external-browser",
)
```

**Why:** Profile parameter causes Config to read ~/.databrickscfg, where auth_type setting overrides your explicit auth_type argument.

## Validation Patterns

### Support Multimodal Message Format

```python
from typing import Union

class ChatMessage(BaseModel):
    role: str
    content: Union[str, list]  # Both string and OpenAI multimodal

    def get_text_content(self) -> str:
        """Extract text from string or multimodal format."""
        if isinstance(self.content, str):
            return self.content

        # Handle [{"text": "...", "type": "text"}, ...]
        text_parts = []
        for item in self.content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))

        return "".join(text_parts)
```

**Why:** OpenAI API supports both string and array of content blocks. Support both for compatibility.

### Add Detailed Validation Error Handlers

```python
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()
    error_details = []

    for error in errors:
        loc = " -> ".join(str(x) for x in error["loc"])
        msg = error["msg"]
        error_details.append(f"{loc}: {msg}")

    error_summary = "; ".join(error_details)

    return JSONResponse(
        status_code=422,
        content={
            "detail": errors,
            "error_summary": error_summary,
            "hint": "Check request format. Common: message content should be string or array.",
        },
    )
```

**Why:** Helpful error messages with hints make debugging faster.

## Quick Reference

| Issue | Solution | Why |
|-------|----------|-----|
| Venv corruption | .gitignore .venv + uv sync | Raycast copies assets, breaks symlinks |
| Path race condition | useState(() => getPath()) | Lazy initialization prevents early access |
| Wrong working directory | cd in wrapper script | uv sync needs pyproject.toml location |
| Missing dependencies | uv sync before uv run | Recreate .venv with fresh install |
| Auth override | Don't pass profile to Config | Profile reads ~/.databrickscfg settings |
| Validation errors | Union[str, list] for content | OpenAI multimodal compatibility |
| Unhelpful errors | Custom error handler with hints | Faster debugging |

## Common Mistakes

**❌ "uv handles venv automatically, no need for .gitignore"**
- Reality: uv creates .venv, but Raycast copies it → corruption

**❌ "The path works in development, no need for lazy init"**
- Reality: Race condition only appears intermittently in production

**❌ "Profile parameter is convenient for auth"**
- Reality: Profile settings override your explicit auth_type

**❌ "String content is fine, that's what examples show"**
- Reality: OpenAI clients may send array format, causing validation errors

## Verification Checklist

Before deploying Raycast extension with Python:

- [ ] Added assets/python/.venv/ to .gitignore
- [ ] Used useState(() => getPath()) for path initialization
- [ ] Wrapper script includes cd to working directory
- [ ] Wrapper script runs uv sync before uv run
- [ ] Config initialization doesn't pass profile when setting auth_type
- [ ] Message validation accepts Union[str, list] for content
- [ ] Error handlers include helpful hints and summaries
- [ ] Referenced https://developers.raycast.com for API patterns

## Real-World Impact

**From production commits:**
- 5987c3b: Fixed venv corruption affecting all users after Raycast asset copy
- 47697f0: Fixed authentication overrides causing "wrong auth type" errors
- 47697f0: Added multimodal support preventing validation failures with OpenAI clients

These patterns prevent production failures that only appear after Raycast's build/copy process.
