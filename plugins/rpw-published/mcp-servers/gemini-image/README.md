# gemini-image MCP Server

Provides image generation and editing tools via Google's Gemini native image generation.

## Authentication

The server uses **Vertex AI authenticated with gcloud Application Default Credentials (ADC)** — an OAuth-based flow. Running `gcloud auth application-default login` completes the Google SSO/OAuth consent once; the `google-genai` SDK then mints and auto-refreshes short-lived access tokens on every call. **No API key, nothing secret on disk.**

## Setup

1. Make sure `gcloud` is installed and ADC is authenticated:
   ```
   gcloud auth application-default login
   ```
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

## Tools

- `generate_image` — Generate an image from a text prompt
- `edit_image` — Edit an existing image with a text instruction

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
