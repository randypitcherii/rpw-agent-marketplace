"""Central registry of MCP servers shipped by rpw-published and how to configure each.

Each server entry declares an ordered list of credential `sources`. At setup
time, the /mcp-setup skill tries each source in order and uses the first
that's available (UC connection exists / secrets scope has the key / gcloud
ADC is authed). Whichever wins gets written into the server's dev.env so
env_loader.py can call the matching resolver at runtime.

Source types:
    uc_connection     — fetch from a Databricks UC connection's user-credentials
    databricks_secrets — fetch from a per-user Databricks secrets scope
    gcloud_adc        — gcloud Application Default Credentials. With a non-empty
                        field_map, fields are read from the ADC JSON into env
                        vars. With an empty field_map ({}), it's a no-op: the
                        credential is consumed at runtime (e.g. the google-genai
                        SDK mints Vertex AI tokens from ADC), and the server's
                        non-secret config comes from extra_env_prompts.

A fourth implicit source, "manual env file", takes over when the skill can't
resolve any declared source — the user fills in literal values in dev.env.
"""

PLUGIN_NAME = "rpw_mcp"  # used to compose secret scope names: <user>_rpw_mcp

# Canonical OAuth contract for every consumer that uses *gcloud Application
# Default Credentials*. This is separate from the gcloud user credential
# (`gcloud auth print-access-token --account`) and UC connections. Calendar,
# Gmail, and standalone Drive use the `google-mcp` UC connection, so are absent.
GOOGLE_ADC_SCOPES: dict[str, dict[str, object]] = {
    "core_identity": {
        "credential_source": "gcloud_adc",
        "scopes": ("openid", "https://www.googleapis.com/auth/userinfo.email"),
    },
    "gemini-image": {
        "credential_source": "gcloud_adc",
        "scopes": ("https://www.googleapis.com/auth/cloud-platform",),
    },
    "google-docs": {
        "credential_source": "gcloud_adc",
        "scopes": (
            "https://www.googleapis.com/auth/documents",
            "https://www.googleapis.com/auth/drive",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/presentations",
        ),
    },
    "google-tasks": {
        "credential_source": "gcloud_adc",
        "scopes": ("https://www.googleapis.com/auth/tasks",),
    },
}


def adc_scope_union(consumers: tuple[str, ...] | list[str] | None = None) -> tuple[str, ...]:
    """Return the deterministic required scope union for enabled ADC consumers."""
    enabled = GOOGLE_ADC_SCOPES.keys() if consumers is None else consumers
    scopes = set()
    for consumer in enabled:
        entry = GOOGLE_ADC_SCOPES[consumer]
        if entry["credential_source"] != "gcloud_adc":
            raise ValueError(f"{consumer} is not an ADC credential consumer")
        scopes.update(entry["scopes"])
    return tuple(sorted(scopes))

SERVERS: dict[str, dict] = {
    "jira": {
        "sources": [
            {
                "type": "uc_proxy",
                "connection_name": "jira-mcp",
            },
        ],
    },
    "gemini-image": {
        # Vertex AI via gcloud ADC (OAuth). The google-genai SDK mints short-lived
        # access tokens at call time — no static key on disk. The gcloud_adc source
        # uses an empty field_map (no-op resolver); the Vertex project/location
        # come from extra_env_prompts below.
        "sources": [
            {
                "type": "gcloud_adc",
                "field_map": {},
            },
        ],
        "extra_env_prompts": {
            "GOOGLE_CLOUD_PROJECT": "GCP project ID with Vertex AI enabled (e.g. my-gcp-project)",
            "GOOGLE_CLOUD_LOCATION": "Vertex AI location (e.g. global)",
        },
    },
    "google-drive": {
        "sources": [
            {
                "type": "uc_proxy",
                "connection_name": "google-mcp",
            },
        ],
    },
    "google-gmail": {
        "sources": [
            {
                "type": "uc_proxy",
                "connection_name": "google-mcp",
            },
        ],
    },
    "google-calendar": {
        "sources": [
            {
                "type": "uc_proxy",
                "connection_name": "google-mcp",
            },
        ],
    },
    "google-tasks": {
        "sources": [
            {
                "type": "gcloud_adc",
                "field_map": {
                    "client_id": "GOOGLE_CLIENT_ID",
                    "client_secret": "GOOGLE_CLIENT_SECRET",
                    "refresh_token": "GOOGLE_REFRESH_TOKEN",
                },
            },
        ],
    },
    "google-docs": {
        "sources": [
            {
                "type": "gcloud_adc",
                "field_map": {},
            },
        ],
        "extra_env_prompts": {
            "GDOCS_QUOTA_PROJECT": "GCP project ID for quota/billing",
            "GDOCS_TARGET_FOLDER_ID": "Drive folder ID for default doc destination",
        },
    },
}
