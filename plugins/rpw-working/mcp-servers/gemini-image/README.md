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
