# gemini-image MCP Server

Provides image generation and editing tools via Google's Gemini native image generation.

## Authentication

The server uses **Vertex AI authenticated with gcloud Application Default Credentials (ADC)** — an OAuth-based flow. Running `gcloud auth application-default login` completes the Google SSO/OAuth consent once; the `google-genai` SDK then mints and auto-refreshes short-lived access tokens on every call. **No API key, nothing secret on disk.**

## Setup

1. Make sure `gcloud` is installed and validate the shared ADC grant:
   ```bash
   cd "$CLAUDE_PLUGIN_ROOT/skills/mcp-setup"
   uv run python google_adc.py
   ```
   The canonical scope registry is `skills/mcp-setup/server_registry.py`. If it
   reports missing scopes, use its generated full-union login command. `--scopes`
   replaces the ADC grant, so a Vertex-only command could break other ADC-backed
   Google MCP servers.
2. Use a GCP project that has the Vertex AI API enabled.
3. Copy `template.env` to `dev.env` (gitignored) and set your own project ID. The defaults already point at Vertex AI:
   ```
   CREDENTIAL_SOURCE=gcloud_adc
   GCLOUD_FIELD_MAP=
   GOOGLE_CLOUD_PROJECT=your-gcp-project-id
   GOOGLE_CLOUD_LOCATION=global
   GOOGLE_CLOUD_QUOTA_PROJECT=your-gcp-project-id
   ```
4. The server is auto-started by the rpw-published plugin and reads `dev.env` at launch.

If `GOOGLE_CLOUD_PROJECT` is unset or ADC is missing/expired, the server fails fast at startup with an actionable message, e.g.:
`❌ gcloud Application Default Credentials not found — run: gcloud auth application-default login`

## Backend: Vertex AI (default) or Databricks

`GEMINI_IMAGE_BACKEND` picks where the call goes. Both backends authenticate with OAuth, and neither stores a key.

| Backend | Auth | Set in `dev.env` |
|---|---|---|
| `vertex` (default) | gcloud ADC, as above | `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` |
| `databricks` | A Databricks CLI profile's OAuth tokens. No Google credential. | `GEMINI_IMAGE_BACKEND=databricks`, `GEMINI_IMAGE_DATABRICKS_PROFILE=<profile>` |

The `databricks` backend calls the Databricks-hosted Foundation Model API endpoints `databricks-gemini-3-1-flash-image` and `databricks-gemini-3-pro-image`. AI Gateway usage tracking applies to every call. These endpoints are global, so a workspace serves them only when cross-Geo processing is allowed (account console → workspace → Security and compliance). A workspace without them answers 404, which the tools report as `invalid_model` with that fix attached.

On this backend the aliases resolve to endpoint names:

| `model` value | Databricks endpoint |
|---|---|
| `gemini-2.5-flash-image` (the default), `nano-banana` | `databricks-gemini-3-1-flash-image`: **a substitution**, 2.5 Flash Image is not hosted on Databricks |
| `gemini-3.1-flash-image`, `nano-banana-2` | `databricks-gemini-3-1-flash-image` |
| `gemini-3-pro-image`, `nano-banana-pro` | `databricks-gemini-3-pro-image` |

Any other `model` value is passed through as a raw endpoint name. The substitution is not silent: every success result's `Usage:` line names both `requested_model` and `resolved_model`. A caller that wants 3.1 Flash Image on Databricks should ask for `gemini-3.1-flash-image` by name.

**Who picks the backend.** `dev.env` loads with `override=True`, so for most keys the file beats the process environment. `GEMINI_IMAGE_BACKEND` and `GEMINI_IMAGE_DATABRICKS_PROFILE` are the exception: a value already set in the environment that launches `run_mcp.py` wins over the file. That lets an app that spawns the server (darkroom does) choose the backend explicitly. With neither key set, the file decides as before.

## Tools

- `generate_image` — Generate an image from a text prompt
- `edit_image` — Edit an existing image with a text instruction

`generate_image` parameters: `prompt`, `filename`, `aspect_ratio` (`1:1`, `3:4`,
`4:3`, `9:16`, `16:9`), `model`, and `image_size` (`1K`, `2K` or `4K`; omit it for
the model default). `image_size` is passed as `image_config.image_size` on both
backends. Gemini 3 image models honor it; Gemini 2.5 Flash Image does not
support it, so pair a size with `nano-banana-2` or `nano-banana-pro`. Any other
value returns an `invalid_image_size` error before a call is made.

A success result is one line, `Image saved to: <path>` (`Edited image saved to:`
for edits). When the backend reports token usage, a second line follows:

```
Image saved to: /tmp/owl.png
Usage: {"backend": "databricks", "completion_tokens": 1120, "image_output_tokens": 1120, "prompt_tokens": 11, "requested_model": "nano-banana-2", "resolved_model": "databricks-gemini-3-1-flash-image"}
```

The counters are the backend's own: the chat-completion `usage` fields on
Databricks; `usage_metadata` on Vertex (`prompt_token_count`,
`candidates_token_count`, `total_token_count`), with `image_output_tokens`
summed from the image-modality candidate tokens. Price an image by
`image_output_tokens`.

Both tools parse the Gemini response structurally and **validate magic bytes
before writing** any file. If the model returns no image — a safety block, a
text-only refusal, or an empty candidate — the tool returns a structured JSON
error (with `finish_reason`, `block_reason`, blocked safety ratings, and the
model's text) instead of persisting corrupt bytes to disk.

## Model selection

Both tools accept a `model` parameter. You can pass a **raw Vertex model id** or
one of these **friendly aliases**:

| Alias             | Vertex model id           | Notes                    |
|-------------------|---------------------------|--------------------------|
| `nano-banana`     | `gemini-2.5-flash-image`  | GA — the default         |
| `nano-banana-2`   | `gemini-3.1-flash-image`  | "Nano Banana 2"          |
| `nano-banana-pro` | `gemini-3-pro-image`      | "Nano Banana Pro"        |

```
generate_image(prompt="an owl", model="nano-banana-2")   # alias
generate_image(prompt="an owl", model="gemini-3-pro-image")  # raw id also fine
```

Newer models roll out per project/region, so availability varies. If Vertex
rejects a model (unknown id, or your project has no access yet), the tool returns
a structured `invalid_model` error that includes the upstream message and the
alias list above — nothing is written to disk.

**Discover which model ids your project can actually use** (aliases are a
convenience, not a guarantee of access):

```bash
# via gcloud
gcloud ai models list --region=<your-location>

# or via the google-genai SDK
GOOGLE_CLOUD_PROJECT=<your-project> uv run python -c "
from google import genai
c = genai.Client(vertexai=True, project='<your-project>', location='global')
for m in c.models.list():
    if 'image' in getattr(m, 'name', '').lower():
        print(m.name)
"
```

## Manual testing

```bash
APP_ENV=dev uv run python run_mcp.py
```
