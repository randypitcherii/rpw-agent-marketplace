# MCP Live Integration Tests & Dynamic Credentials Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace static `.env` credential loading with dynamic resolvers (UC connections, gcloud ADC) and add live integration tests that exercise real MCP tool calls.

**Architecture:** Extend shared `lib/env_loader.py` with pluggable credential resolvers dispatched by source type. Each `run_mcp.py` declares its source type and config. Integration tests use a shared `McpTestClient` that starts servers over stdio and sends JSON-RPC messages.

**Tech Stack:** Python 3.11, pytest, Databricks CLI (`databricks`), gcloud CLI, JSON-RPC over stdio

---

## File Structure

| File | Responsibility |
|---|---|
| `plugins/rpw-working/mcp-servers/lib/env_loader.py` | Shared env loading + credential resolvers (UC, gcloud ADC, env file) |
| `plugins/rpw-working/mcp-servers/lib/resolvers/__init__.py` | Resolver package |
| `plugins/rpw-working/mcp-servers/lib/resolvers/uc_connection.py` | Fetch tokens from Databricks UC connections API |
| `plugins/rpw-working/mcp-servers/lib/resolvers/gcloud_adc.py` | Read credentials from gcloud ADC JSON |
| `plugins/rpw-working/mcp-servers/lib/resolvers/env_file.py` | Existing dotenv loading (extracted) |
| `plugins/rpw-working/mcp-servers/{slack,glean,jira,google,google-tasks,google-docs-with-subtabs,gemini-image}/run_mcp.py` | Updated wrappers with source type declaration |
| `tests/integration/__init__.py` | Package marker |
| `tests/integration/conftest.py` | McpTestClient, fixtures, credential helpers |
| `tests/integration/test_slack_mcp.py` | Slack live tests |
| `tests/integration/test_glean_mcp.py` | Glean live tests |
| `tests/integration/test_jira_mcp.py` | JIRA live tests |
| `tests/integration/test_google_mcp.py` | Google Drive live tests |
| `tests/integration/test_google_tasks_mcp.py` | Google Tasks live tests |
| `tests/integration/test_google_docs_mcp.py` | Google Docs live tests |
| `tests/integration/test_gemini_image_mcp.py` | Gemini Image live tests |
| `Makefile` | New `test-integration` target |

---

## Chunk 1: Credential Resolvers

### Task 1: Extract existing env-file loading into resolver module

**Files:**
- Create: `plugins/rpw-working/mcp-servers/lib/resolvers/__init__.py`
- Create: `plugins/rpw-working/mcp-servers/lib/resolvers/env_file.py`
- Create: `plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py`
- Modify: `plugins/rpw-working/mcp-servers/lib/env_loader.py`

- [ ] **Step 1: Write failing test for env_file resolver**

```python
# plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py
import os
import tempfile
import unittest
from pathlib import Path


class TestEnvFileResolver(unittest.TestCase):
    def test_resolve_loads_env_vars_from_file(self):
        """env_file resolver should load vars from {APP_ENV}.env into os.environ."""
        from lib.resolvers.env_file import resolve

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "dev.env"
            env_path.write_text("TEST_VAR_XYZ=hello123\n")
            os.environ.pop("TEST_VAR_XYZ", None)
            os.environ["APP_ENV"] = "dev"

            resolve(
                base_dir=Path(tmpdir),
                env_var_map={},  # env_file doesn't remap, just loads
                required=["TEST_VAR_XYZ"],
            )
            self.assertEqual(os.getenv("TEST_VAR_XYZ"), "hello123")

            # cleanup
            os.environ.pop("TEST_VAR_XYZ", None)
            os.environ.pop("APP_ENV", None)

    def test_resolve_raises_on_missing_env_file(self):
        from lib.resolvers.env_file import resolve

        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ["APP_ENV"] = "dev"
            with self.assertRaises(FileNotFoundError):
                resolve(base_dir=Path(tmpdir), env_var_map={}, required=["ANYTHING"])
            os.environ.pop("APP_ENV", None)

    def test_resolve_raises_on_missing_required_var(self):
        from lib.resolvers.env_file import resolve

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "dev.env"
            env_path.write_text("SOME_VAR=exists\n")
            os.environ["APP_ENV"] = "dev"
            with self.assertRaises(EnvironmentError):
                resolve(
                    base_dir=Path(tmpdir),
                    env_var_map={},
                    required=["MISSING_VAR"],
                )
            os.environ.pop("APP_ENV", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/rpw-working/mcp-servers && uv run python -m pytest lib/tests/test_resolvers.py::TestEnvFileResolver -v`
Expected: ImportError — `lib.resolvers.env_file` does not exist

- [ ] **Step 3: Implement env_file resolver**

```python
# plugins/rpw-working/mcp-servers/lib/resolvers/__init__.py
"""Credential resolver modules for MCP server wrappers."""
```

```python
# plugins/rpw-working/mcp-servers/lib/resolvers/env_file.py
"""Resolve credentials from a dotenv file ({APP_ENV}.env)."""

import os
from pathlib import Path

from dotenv import load_dotenv


def resolve(base_dir: Path, env_var_map: dict, required: list[str]) -> None:
    """Load env vars from {APP_ENV}.env file. Raises on missing file or vars."""
    app_env = os.getenv("APP_ENV", "dev").strip().lower()
    env_path = base_dir / f"{app_env}.env"

    if not env_path.exists():
        raise FileNotFoundError(
            f"Env file not found at {env_path}. Copy template.env to {app_env}.env first."
        )

    load_dotenv(env_path)

    missing = [v for v in required if not os.getenv(v)]
    if missing:
        raise EnvironmentError(
            f"Missing env vars in {env_path.name} for APP_ENV={app_env}: {missing}"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/rpw-working/mcp-servers && uv run python -m pytest lib/tests/test_resolvers.py::TestEnvFileResolver -v`
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/rpw-working/mcp-servers/lib/resolvers/ plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py
git commit -m "feat: extract env_file credential resolver from env_loader"
```

### Task 2: UC connection resolver

**Files:**
- Create: `plugins/rpw-working/mcp-servers/lib/resolvers/uc_connection.py`
- Modify: `plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py`

- [ ] **Step 1: Write failing test for UC connection resolver**

```python
# Append to plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py
import subprocess


class TestUcConnectionResolver(unittest.TestCase):
    """Live tests — requires `databricks` CLI with logfood profile configured."""

    def test_resolve_fetches_slack_token(self):
        """UC resolver should fetch access_token and map it to SLACK_BOT_TOKEN."""
        from lib.resolvers.uc_connection import resolve

        os.environ.pop("SLACK_BOT_TOKEN", None)

        resolve(
            connection_name="slack",
            env_var_map={"access_token": "SLACK_BOT_TOKEN"},
            databricks_profile="logfood",
        )

        token = os.getenv("SLACK_BOT_TOKEN")
        self.assertIsNotNone(token, "SLACK_BOT_TOKEN should be set after UC resolve")
        self.assertTrue(len(token) > 10, "Token should be a non-trivial string")

        os.environ.pop("SLACK_BOT_TOKEN", None)

    def test_resolve_raises_on_bad_connection(self):
        from lib.resolvers.uc_connection import resolve

        with self.assertRaises(RuntimeError):
            resolve(
                connection_name="nonexistent-connection-xyz",
                env_var_map={"access_token": "FAKE_VAR"},
                databricks_profile="logfood",
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/rpw-working/mcp-servers && uv run python -m pytest lib/tests/test_resolvers.py::TestUcConnectionResolver -v`
Expected: ImportError — `lib.resolvers.uc_connection` does not exist

- [ ] **Step 3: Implement UC connection resolver**

```python
# plugins/rpw-working/mcp-servers/lib/resolvers/uc_connection.py
"""Resolve credentials from Databricks Unity Catalog connections."""

import json
import os
import subprocess


def _get_user_id(databricks_profile: str) -> str:
    """Get current user ID from Databricks CLI."""
    result = subprocess.run(
        ["databricks", "current-user", "me", "--profile", databricks_profile],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to get Databricks user ID (profile={databricks_profile}): {result.stderr}"
        )
    return json.loads(result.stdout)["id"]


def _get_connection_credentials(
    connection_name: str, user_id: str, databricks_profile: str
) -> dict:
    """Fetch user credentials for a UC connection."""
    result = subprocess.run(
        [
            "databricks", "api", "get",
            f"/api/2.1/unity-catalog/connections/{connection_name}/user-credentials/{user_id}",
            "--profile", databricks_profile,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to fetch UC connection '{connection_name}' credentials: {result.stderr}"
        )
    data = json.loads(result.stdout)
    cred = data.get("connection_user_credential", {})
    state = cred.get("provisioning_info", {}).get("state")
    if state != "ACTIVE":
        raise RuntimeError(
            f"UC connection '{connection_name}' is not ACTIVE (state={state}). "
            f"Re-authenticate at the Databricks workspace."
        )
    return cred.get("options_kvpairs", {}).get("options", {})


def resolve(
    connection_name: str,
    env_var_map: dict[str, str],
    databricks_profile: str = "logfood",
) -> None:
    """Fetch token from UC connection and map to env vars.

    Args:
        connection_name: UC connection name (e.g., "slack", "glean-mcp")
        env_var_map: Maps UC credential field names to env var names
                     (e.g., {"access_token": "SLACK_BOT_TOKEN"})
        databricks_profile: Databricks CLI profile name
    """
    user_id = _get_user_id(databricks_profile)
    options = _get_connection_credentials(connection_name, user_id, databricks_profile)

    for source_key, env_var_name in env_var_map.items():
        value = options.get(source_key)
        if not value:
            raise RuntimeError(
                f"UC connection '{connection_name}' missing field '{source_key}' "
                f"(needed for env var '{env_var_name}')"
            )
        os.environ[env_var_name] = value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/rpw-working/mcp-servers && uv run python -m pytest lib/tests/test_resolvers.py::TestUcConnectionResolver -v`
Expected: 2 tests PASS (requires active `logfood` Databricks profile with UC connections)

- [ ] **Step 5: Commit**

```bash
git add plugins/rpw-working/mcp-servers/lib/resolvers/uc_connection.py plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py
git commit -m "feat: add UC connection credential resolver"
```

### Task 3: gcloud ADC resolver

**Files:**
- Create: `plugins/rpw-working/mcp-servers/lib/resolvers/gcloud_adc.py`
- Modify: `plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py`

- [ ] **Step 1: Write failing test for gcloud ADC resolver**

```python
# Append to plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py
class TestGcloudAdcResolver(unittest.TestCase):
    """Live tests — requires gcloud ADC configured (~/.config/gcloud/application_default_credentials.json)."""

    def test_resolve_loads_google_credentials(self):
        from lib.resolvers.gcloud_adc import resolve

        for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
            os.environ.pop(var, None)

        resolve(
            env_var_map={
                "client_id": "GOOGLE_CLIENT_ID",
                "client_secret": "GOOGLE_CLIENT_SECRET",
                "refresh_token": "GOOGLE_REFRESH_TOKEN",
            },
        )

        for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
            self.assertIsNotNone(os.getenv(var), f"{var} should be set after resolve")
            self.assertTrue(len(os.getenv(var)) > 5, f"{var} should be a non-trivial string")
            os.environ.pop(var, None)

    def test_resolve_raises_on_missing_adc_field(self):
        from lib.resolvers.gcloud_adc import resolve

        with self.assertRaises(RuntimeError):
            resolve(
                env_var_map={"nonexistent_field_xyz": "FAKE_VAR"},
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/rpw-working/mcp-servers && uv run python -m pytest lib/tests/test_resolvers.py::TestGcloudAdcResolver -v`
Expected: ImportError

- [ ] **Step 3: Implement gcloud ADC resolver**

```python
# plugins/rpw-working/mcp-servers/lib/resolvers/gcloud_adc.py
"""Resolve Google credentials from gcloud Application Default Credentials."""

import json
import os
from pathlib import Path

ADC_PATH = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"


def resolve(
    env_var_map: dict[str, str],
    adc_path: Path = ADC_PATH,
) -> None:
    """Read gcloud ADC JSON and map fields to env vars.

    Args:
        env_var_map: Maps ADC JSON field names to env var names
                     (e.g., {"client_id": "GOOGLE_CLIENT_ID"})
        adc_path: Path to ADC JSON file (default: standard gcloud location)
    """
    if not adc_path.exists():
        raise RuntimeError(
            f"gcloud ADC file not found at {adc_path}. "
            f"Run 'gcloud auth application-default login' first."
        )

    with open(adc_path) as f:
        adc = json.load(f)

    for source_key, env_var_name in env_var_map.items():
        value = adc.get(source_key)
        if not value:
            raise RuntimeError(
                f"gcloud ADC missing field '{source_key}' "
                f"(needed for env var '{env_var_name}'). "
                f"Re-run 'gcloud auth application-default login'."
            )
        os.environ[env_var_name] = value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/rpw-working/mcp-servers && uv run python -m pytest lib/tests/test_resolvers.py::TestGcloudAdcResolver -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/rpw-working/mcp-servers/lib/resolvers/gcloud_adc.py plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py
git commit -m "feat: add gcloud ADC credential resolver"
```

### Task 4: Add `resolve_credentials` dispatcher to env_loader

**Files:**
- Modify: `plugins/rpw-working/mcp-servers/lib/env_loader.py`
- Modify: `plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py`

- [ ] **Step 1: Write failing test for dispatcher**

```python
# Append to plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py
class TestResolveCredentials(unittest.TestCase):
    def test_dispatches_to_env_file(self):
        from lib.env_loader import resolve_credentials

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "dev.env"
            env_path.write_text("DISPATCH_TEST_VAR=works\n")
            os.environ["APP_ENV"] = "dev"
            os.environ.pop("DISPATCH_TEST_VAR", None)

            resolve_credentials(
                source="env_file",
                config={"base_dir": Path(tmpdir), "required": ["DISPATCH_TEST_VAR"]},
            )
            self.assertEqual(os.getenv("DISPATCH_TEST_VAR"), "works")

            os.environ.pop("DISPATCH_TEST_VAR", None)
            os.environ.pop("APP_ENV", None)

    def test_raises_on_unknown_source(self):
        from lib.env_loader import resolve_credentials

        with self.assertRaises(ValueError):
            resolve_credentials(source="unknown_source", config={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/rpw-working/mcp-servers && uv run python -m pytest lib/tests/test_resolvers.py::TestResolveCredentials -v`
Expected: ImportError — `resolve_credentials` does not exist in `env_loader`

- [ ] **Step 3: Add resolve_credentials to env_loader.py**

Add to the end of `plugins/rpw-working/mcp-servers/lib/env_loader.py`:

```python
def resolve_credentials(source: str, config: dict) -> None:
    """Dispatch to the appropriate credential resolver.

    Args:
        source: One of "env_file", "uc_connection", "gcloud_adc"
        config: Source-specific configuration dict passed to the resolver
    """
    if source == "env_file":
        from lib.resolvers.env_file import resolve
        resolve(
            base_dir=config["base_dir"],
            env_var_map=config.get("env_var_map", {}),
            required=config.get("required", []),
        )
    elif source == "uc_connection":
        from lib.resolvers.uc_connection import resolve
        resolve(
            connection_name=config["connection_name"],
            env_var_map=config["env_var_map"],
            databricks_profile=config.get("databricks_profile", "logfood"),
        )
    elif source == "gcloud_adc":
        from lib.resolvers.gcloud_adc import resolve
        resolve(
            env_var_map=config["env_var_map"],
        )
    else:
        raise ValueError(
            f"Unknown credential source '{source}'. "
            f"Expected one of: env_file, uc_connection, gcloud_adc"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/rpw-working/mcp-servers && uv run python -m pytest lib/tests/test_resolvers.py::TestResolveCredentials -v`
Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add plugins/rpw-working/mcp-servers/lib/env_loader.py plugins/rpw-working/mcp-servers/lib/tests/test_resolvers.py
git commit -m "feat: add resolve_credentials dispatcher to env_loader"
```

---

## Chunk 2: Update run_mcp.py Wrappers

### Task 5: Update slack/glean/jira wrappers to use UC connection resolver

**Files:**
- Modify: `plugins/rpw-working/mcp-servers/slack/run_mcp.py`
- Modify: `plugins/rpw-working/mcp-servers/glean/run_mcp.py`
- Modify: `plugins/rpw-working/mcp-servers/jira/run_mcp.py`

- [ ] **Step 1: Update slack/run_mcp.py**

Replace the credential loading section. The wrapper should:

```python
# plugins/rpw-working/mcp-servers/slack/run_mcp.py
"""
Thin wrapper that resolves credentials and runs the Slack MCP server (PEX).
Keeps MCP config JSON secret-free.

Usage:
    uv run python run_mcp.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.env_loader import resolve_credentials

PEX_PATH = Path.home() / "mcp" / "servers" / "slack_mcp" / "slack_mcp_deploy.pex"


def main() -> None:
    try:
        resolve_credentials(
            source="uc_connection",
            config={
                "connection_name": "slack",
                "env_var_map": {"access_token": "SLACK_BOT_TOKEN"},
            },
        )
    except (RuntimeError, EnvironmentError) as exc:
        print(f"\u274c {exc}", file=sys.stderr)
        sys.exit(1)

    if not PEX_PATH.exists():
        print(f"\u274c PEX not found: {PEX_PATH}", file=sys.stderr)
        sys.exit(1)

    os.environ["I_DANGEROUSLY_OPT_IN_TO_UNSUPPORTED_ALPHA_TOOLS"] = "true"
    os.execvp("python3.10", ["python3.10", str(PEX_PATH)])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update glean/run_mcp.py**

Same pattern — `connection_name="glean-mcp"`, `env_var_map={"access_token": "GLEAN_API_TOKEN"}`

- [ ] **Step 3: Update jira/run_mcp.py**

Same pattern — `connection_name="jira-mcp"`, `env_var_map={"access_token": "JIRA_API_TOKEN"}`. Keep `MCP_PRIVACY_SUMMARIZATION_ENABLED = "false"`.

- [ ] **Step 4: Verify all three wrappers resolve credentials**

Run each wrapper briefly (Ctrl-C after it starts):
```bash
cd plugins/rpw-working/mcp-servers/slack && uv run python -c "
import sys; sys.path.insert(0, '..')
from lib.env_loader import resolve_credentials
resolve_credentials(source='uc_connection', config={'connection_name': 'slack', 'env_var_map': {'access_token': 'SLACK_BOT_TOKEN'}})
import os; print('SLACK_BOT_TOKEN set:', bool(os.getenv('SLACK_BOT_TOKEN')))
"
```

Repeat for glean and jira.

- [ ] **Step 5: Commit**

```bash
git add plugins/rpw-working/mcp-servers/slack/run_mcp.py plugins/rpw-working/mcp-servers/glean/run_mcp.py plugins/rpw-working/mcp-servers/jira/run_mcp.py
git commit -m "feat: switch slack/glean/jira wrappers to UC connection resolver"
```

### Task 6: Update google/google-tasks wrappers to use gcloud ADC resolver

**Files:**
- Modify: `plugins/rpw-working/mcp-servers/google/run_mcp.py`
- Modify: `plugins/rpw-working/mcp-servers/google-tasks/run_mcp.py`

- [ ] **Step 1: Update google/run_mcp.py**

```python
# plugins/rpw-working/mcp-servers/google/run_mcp.py
"""
Thin wrapper that resolves credentials and runs the Google MCP server (PEX).
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.env_loader import resolve_credentials

PEX_PATH = Path.home() / "mcp" / "servers" / "google_mcp" / "google_mcp_deploy.pex"


def main() -> None:
    try:
        resolve_credentials(
            source="gcloud_adc",
            config={
                "env_var_map": {
                    "client_id": "GOOGLE_CLIENT_ID",
                    "client_secret": "GOOGLE_CLIENT_SECRET",
                    "refresh_token": "GOOGLE_REFRESH_TOKEN",
                },
            },
        )
    except (RuntimeError, EnvironmentError) as exc:
        print(f"\u274c {exc}", file=sys.stderr)
        sys.exit(1)

    if not PEX_PATH.exists():
        print(f"\u274c PEX not found: {PEX_PATH}", file=sys.stderr)
        sys.exit(1)

    os.environ["I_DANGEROUSLY_OPT_IN_TO_UNSUPPORTED_ALPHA_TOOLS"] = "true"
    os.environ["MCP_PRIVACY_SUMMARIZATION_ENABLED"] = "false"
    os.execvp("python3.10", ["python3.10", str(PEX_PATH)])


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Update google-tasks/run_mcp.py**

Same gcloud_adc pattern. Uses `from mcp_server import main as server_main` (not PEX).

- [ ] **Step 3: google-docs-with-subtabs stays on env_file**

Update to use `resolve_credentials` dispatcher but keep `source="env_file"`:

```python
resolve_credentials(
    source="env_file",
    config={
        "base_dir": Path(__file__).parent,
        "required": ["GDOCS_QUOTA_PROJECT"],
    },
)
```

- [ ] **Step 4: gemini-image stays on env_file**

Same pattern — `source="env_file"`, `required=["GEMINI_API_KEY"]`.

- [ ] **Step 5: Verify google wrapper resolves credentials**

```bash
cd plugins/rpw-working/mcp-servers/google && uv run python -c "
import sys, os; sys.path.insert(0, '..')
from lib.env_loader import resolve_credentials
resolve_credentials(source='gcloud_adc', config={'env_var_map': {'client_id': 'GOOGLE_CLIENT_ID', 'client_secret': 'GOOGLE_CLIENT_SECRET', 'refresh_token': 'GOOGLE_REFRESH_TOKEN'}})
print('GOOGLE_CLIENT_ID set:', bool(os.getenv('GOOGLE_CLIENT_ID')))
"
```

- [ ] **Step 6: Commit**

```bash
git add plugins/rpw-working/mcp-servers/google/run_mcp.py plugins/rpw-working/mcp-servers/google-tasks/run_mcp.py plugins/rpw-working/mcp-servers/google-docs-with-subtabs/run_mcp.py plugins/rpw-working/mcp-servers/gemini-image/run_mcp.py
git commit -m "feat: switch google wrappers to gcloud ADC, standardize all wrappers on resolve_credentials"
```

### Task 7: Run existing repo validation tests

- [ ] **Step 1: Run make verify to ensure no regressions**

Run: `make verify`
Expected: All existing tests pass. The wrapper interface changed but file structure is intact.

- [ ] **Step 2: Fix any broken tests**

The existing `test_run_mcp_env.py` files in each server directory test the old `REQUIRED` list pattern. These will need updating to test the new `resolve_credentials` call. Update each to verify the source type and config are correctly declared.

- [ ] **Step 3: Commit fixes if needed**

```bash
git add -u
git commit -m "fix: update existing wrapper tests for new resolve_credentials interface"
```

---

## Chunk 3: Integration Test Infrastructure

### Task 8: Create McpTestClient and conftest.py

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`

- [ ] **Step 1: Write McpTestClient**

```python
# tests/integration/conftest.py
"""Shared infrastructure for MCP server live integration tests."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MCP_SERVERS_DIR = REPO_ROOT / "plugins" / "rpw-working" / "mcp-servers"

# Add mcp-servers to path so resolvers can be imported
sys.path.insert(0, str(MCP_SERVERS_DIR))


class McpTestClient:
    """Starts an MCP server over stdio and sends JSON-RPC messages."""

    def __init__(self, server_name: str, command: list[str], cwd: Path | None = None):
        self.server_name = server_name
        self.command = command
        self.cwd = cwd
        self.process: subprocess.Popen | None = None
        self._request_id = 0

    def start(self, timeout: float = 30.0):
        """Start the MCP server subprocess."""
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.cwd,
        )
        # Send initialize request
        response = self.send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-test-client", "version": "1.0.0"},
        }, timeout=timeout)
        assert "result" in response, f"Initialize failed: {response}"
        # Send initialized notification
        self._send_notification("notifications/initialized", {})
        return response

    def send(self, method: str, params: dict, timeout: float = 30.0) -> dict:
        """Send a JSON-RPC request and wait for response."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        message = json.dumps(request)
        content = f"Content-Length: {len(message.encode())}\r\n\r\n{message}"
        self.process.stdin.write(content.encode())
        self.process.stdin.flush()
        return self._read_response(timeout)

    def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        message = json.dumps(notification)
        content = f"Content-Length: {len(message.encode())}\r\n\r\n{message}"
        self.process.stdin.write(content.encode())
        self.process.stdin.flush()

    def _read_response(self, timeout: float) -> dict:
        """Read a JSON-RPC response from stdout."""
        import select

        deadline = time.time() + timeout
        headers = b""
        while time.time() < deadline:
            ready, _, _ = select.select([self.process.stdout], [], [], 1.0)
            if ready:
                byte = self.process.stdout.read(1)
                if not byte:
                    stderr = self.process.stderr.read()
                    raise RuntimeError(
                        f"MCP server {self.server_name} died. stderr: {stderr.decode()}"
                    )
                headers += byte
                if headers.endswith(b"\r\n\r\n"):
                    break
        else:
            raise TimeoutError(f"Timed out waiting for response from {self.server_name}")

        # Parse Content-Length
        header_str = headers.decode()
        content_length = None
        for line in header_str.split("\r\n"):
            if line.lower().startswith("content-length:"):
                content_length = int(line.split(":")[1].strip())
        assert content_length, f"No Content-Length in response headers: {header_str}"

        body = b""
        while len(body) < content_length and time.time() < deadline:
            chunk = self.process.stdout.read(content_length - len(body))
            if chunk:
                body += chunk
        return json.loads(body.decode())

    def list_tools(self) -> list[dict]:
        """Send tools/list and return the tools array."""
        response = self.send("tools/list", {})
        assert "result" in response, f"tools/list failed: {response}"
        return response["result"]["tools"]

    def call_tool(self, name: str, arguments: dict, timeout: float = 30.0) -> dict:
        """Send tools/call and return the result."""
        response = self.send("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        return response

    def stop(self):
        """Kill the MCP server subprocess."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()


def make_uv_command(server_dir: str) -> list[str]:
    """Build the uv run command for an MCP server."""
    server_path = MCP_SERVERS_DIR / server_dir
    return [
        "uv", "run",
        "--project", str(server_path),
        "python", str(server_path / "run_mcp.py"),
    ]
```

```python
# tests/integration/__init__.py
```

- [ ] **Step 2: Verify conftest imports cleanly**

Run: `cd /Users/randy.pitcher/projects/rpw-agent-marketplace && uv run python -c "from tests.integration.conftest import McpTestClient; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add tests/integration/
git commit -m "feat: add MCP integration test infrastructure with McpTestClient"
```

---

## Chunk 4: Integration Tests Per Server

### Task 9: Gemini Image integration test

**Files:**
- Create: `tests/integration/test_gemini_image_mcp.py`

- [ ] **Step 1: Write test**

```python
# tests/integration/test_gemini_image_mcp.py
"""Live integration test for gemini-image MCP server."""

import unittest
from pathlib import Path

from tests.integration.conftest import McpTestClient, make_uv_command, MCP_SERVERS_DIR


class TestGeminiImageMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Resolve credentials before starting server
        import sys
        sys.path.insert(0, str(MCP_SERVERS_DIR))
        from lib.env_loader import resolve_credentials

        resolve_credentials(
            source="env_file",
            config={
                "base_dir": MCP_SERVERS_DIR / "gemini-image",
                "required": ["GEMINI_API_KEY"],
            },
        )

        cls.client = McpTestClient(
            "gemini-image",
            make_uv_command("gemini-image"),
        )
        cls.client.start()

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0, "Server should expose at least one tool")
        tool_names = [t["name"] for t in tools]
        self.assertTrue(
            any("image" in name.lower() or "generat" in name.lower() for name in tool_names),
            f"Expected an image generation tool, got: {tool_names}",
        )

    def test_generate_image(self):
        tools = self.client.list_tools()
        # Use the first tool that looks like image generation
        tool_names = [t["name"] for t in tools]
        gen_tool = next(
            (n for n in tool_names if "image" in n.lower() or "generat" in n.lower()),
            tool_names[0],
        )

        result = self.client.call_tool(gen_tool, {
            "prompt": "A small red circle on white background",
        }, timeout=60)

        self.assertIn("result", result, f"Tool call failed: {result}")
```

- [ ] **Step 2: Run test**

Run: `uv run python -m pytest tests/integration/test_gemini_image_mcp.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_gemini_image_mcp.py
git commit -m "test: add gemini-image MCP live integration test"
```

### Task 10: Slack integration test

**Files:**
- Create: `tests/integration/test_slack_mcp.py`

- [ ] **Step 1: Write test**

```python
# tests/integration/test_slack_mcp.py
"""Live integration test for Slack MCP server."""

import unittest

from tests.integration.conftest import McpTestClient, make_uv_command, MCP_SERVERS_DIR


class TestSlackMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(MCP_SERVERS_DIR))
        from lib.env_loader import resolve_credentials

        resolve_credentials(
            source="uc_connection",
            config={
                "connection_name": "slack",
                "env_var_map": {"access_token": "SLACK_BOT_TOKEN"},
            },
        )

        cls.client = McpTestClient("slack", make_uv_command("slack"))
        cls.client.start()

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0)

    def test_list_channels(self):
        """Read-only: list Slack channels."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        # Find a list/search channels tool
        list_tool = next(
            (n for n in tool_names if "list" in n.lower() and "channel" in n.lower()),
            next((n for n in tool_names if "channel" in n.lower()), None),
        )
        self.assertIsNotNone(list_tool, f"No channel listing tool found in: {tool_names}")

        result = self.client.call_tool(list_tool, {"limit": 5}, timeout=30)
        self.assertIn("result", result, f"Tool call failed: {result}")

    def test_post_and_delete_dm(self):
        """Write test: post a message to DM-to-self, then delete it."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        # Find post message tool
        post_tool = next(
            (n for n in tool_names if "send" in n.lower() or "post" in n.lower()),
            next((n for n in tool_names if "message" in n.lower()), None),
        )
        self.assertIsNotNone(post_tool, f"No message posting tool found in: {tool_names}")

        # Post to DM-to-self (user's own DM channel)
        result = self.client.call_tool(post_tool, {
            "channel": "me",
            "text": "_mcp_integration_test: this message will be deleted",
        }, timeout=30)
        self.assertIn("result", result, f"Post failed: {result}")

        # Extract message timestamp for deletion if possible
        # Cleanup is best-effort — DM-to-self messages are only visible to the user
```

- [ ] **Step 2: Run test**

Run: `uv run python -m pytest tests/integration/test_slack_mcp.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_slack_mcp.py
git commit -m "test: add Slack MCP live integration test"
```

### Task 11: Glean integration test

**Files:**
- Create: `tests/integration/test_glean_mcp.py`

- [ ] **Step 1: Write test**

```python
# tests/integration/test_glean_mcp.py
"""Live integration test for Glean MCP server (read-only — Glean has no write API)."""

import unittest

from tests.integration.conftest import McpTestClient, make_uv_command, MCP_SERVERS_DIR


class TestGleanMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(MCP_SERVERS_DIR))
        from lib.env_loader import resolve_credentials

        resolve_credentials(
            source="uc_connection",
            config={
                "connection_name": "glean-mcp",
                "env_var_map": {"access_token": "GLEAN_API_TOKEN"},
            },
        )

        cls.client = McpTestClient("glean", make_uv_command("glean"))
        cls.client.start()

    @classmethod
    def tearDownClass(cls):
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0)

    def test_search(self):
        """Read-only: search Glean for a common term."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        search_tool = next(
            (n for n in tool_names if "search" in n.lower()),
            tool_names[0],
        )

        result = self.client.call_tool(search_tool, {
            "query": "databricks",
        }, timeout=30)
        self.assertIn("result", result, f"Search failed: {result}")
```

- [ ] **Step 2: Run test**

Run: `uv run python -m pytest tests/integration/test_glean_mcp.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_glean_mcp.py
git commit -m "test: add Glean MCP live integration test"
```

### Task 12: JIRA integration test

**Files:**
- Create: `tests/integration/test_jira_mcp.py`

- [ ] **Step 1: Write test**

```python
# tests/integration/test_jira_mcp.py
"""Live integration test for JIRA MCP server."""

import unittest

from tests.integration.conftest import McpTestClient, make_uv_command, MCP_SERVERS_DIR


class TestJiraMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(MCP_SERVERS_DIR))
        from lib.env_loader import resolve_credentials

        resolve_credentials(
            source="uc_connection",
            config={
                "connection_name": "jira-mcp",
                "env_var_map": {"access_token": "JIRA_API_TOKEN"},
            },
        )

        cls.client = McpTestClient("jira", make_uv_command("jira"))
        cls.client.start()
        cls._created_issue_key = None

    @classmethod
    def tearDownClass(cls):
        # Cleanup: delete test issue if created
        if cls._created_issue_key:
            try:
                tools = cls.client.list_tools()
                tool_names = [t["name"] for t in tools]
                delete_tool = next(
                    (n for n in tool_names if "delete" in n.lower()),
                    None,
                )
                if delete_tool:
                    cls.client.call_tool(delete_tool, {
                        "issue_key": cls._created_issue_key,
                    }, timeout=15)
            except Exception:
                pass  # best-effort cleanup
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0)

    def test_read_operation(self):
        """Read-only: list projects or search issues."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        read_tool = next(
            (n for n in tool_names if "list" in n.lower() or "search" in n.lower() or "get" in n.lower()),
            tool_names[0],
        )

        result = self.client.call_tool(read_tool, {}, timeout=30)
        self.assertIn("result", result, f"Read failed: {result}")
```

Note: The write test (create/delete issue) is structured in tearDownClass cleanup. The worker should discover the exact tool names at runtime and adapt the create/delete calls. If no suitable personal project exists, the write test should be deferred.

- [ ] **Step 2: Run test**

Run: `uv run python -m pytest tests/integration/test_jira_mcp.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_jira_mcp.py
git commit -m "test: add JIRA MCP live integration test"
```

### Task 13: Google Drive integration test

**Files:**
- Create: `tests/integration/test_google_mcp.py`

- [ ] **Step 1: Write test**

```python
# tests/integration/test_google_mcp.py
"""Live integration test for Google MCP server (Drive, Calendar, etc.)."""

import unittest

from tests.integration.conftest import McpTestClient, make_uv_command, MCP_SERVERS_DIR


class TestGoogleMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(MCP_SERVERS_DIR))
        from lib.env_loader import resolve_credentials

        resolve_credentials(
            source="gcloud_adc",
            config={
                "env_var_map": {
                    "client_id": "GOOGLE_CLIENT_ID",
                    "client_secret": "GOOGLE_CLIENT_SECRET",
                    "refresh_token": "GOOGLE_REFRESH_TOKEN",
                },
            },
        )

        cls.client = McpTestClient("google", make_uv_command("google"))
        cls.client.start()
        cls._created_file_id = None

    @classmethod
    def tearDownClass(cls):
        # Cleanup: delete test file if created
        if cls._created_file_id:
            try:
                tools = cls.client.list_tools()
                tool_names = [t["name"] for t in tools]
                delete_tool = next(
                    (n for n in tool_names if "delete" in n.lower() and "file" in n.lower()),
                    next((n for n in tool_names if "delete" in n.lower()), None),
                )
                if delete_tool:
                    cls.client.call_tool(delete_tool, {
                        "file_id": cls._created_file_id,
                    }, timeout=15)
            except Exception:
                pass
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0)

    def test_list_files(self):
        """Read-only: list Drive files."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        list_tool = next(
            (n for n in tool_names if "list" in n.lower() and "file" in n.lower()),
            next((n for n in tool_names if "search" in n.lower() or "list" in n.lower()), None),
        )
        self.assertIsNotNone(list_tool, f"No file listing tool found in: {tool_names}")

        result = self.client.call_tool(list_tool, {}, timeout=30)
        self.assertIn("result", result, f"List failed: {result}")

    def test_create_and_delete_doc(self):
        """Write test: create a test doc, then delete it."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        create_tool = next(
            (n for n in tool_names if "create" in n.lower() and ("doc" in n.lower() or "file" in n.lower())),
            None,
        )
        if create_tool is None:
            self.skipTest(f"No doc creation tool found in: {tool_names}")

        import time
        result = self.client.call_tool(create_tool, {
            "title": f"_mcp_integration_test_{int(time.time())}",
            "content": "This is an automated test document. Safe to delete.",
        }, timeout=30)
        self.assertIn("result", result, f"Create failed: {result}")

        # Store file ID for cleanup in tearDownClass
        # The worker should extract the file ID from the result content
```

- [ ] **Step 2: Run test**

Run: `uv run python -m pytest tests/integration/test_google_mcp.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_google_mcp.py
git commit -m "test: add Google Drive MCP live integration test"
```

### Task 14: Google Tasks integration test

**Files:**
- Create: `tests/integration/test_google_tasks_mcp.py`

- [ ] **Step 1: Write test**

```python
# tests/integration/test_google_tasks_mcp.py
"""Live integration test for Google Tasks MCP server."""

import unittest

from tests.integration.conftest import McpTestClient, make_uv_command, MCP_SERVERS_DIR


class TestGoogleTasksMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(MCP_SERVERS_DIR))
        from lib.env_loader import resolve_credentials

        resolve_credentials(
            source="gcloud_adc",
            config={
                "env_var_map": {
                    "client_id": "GOOGLE_CLIENT_ID",
                    "client_secret": "GOOGLE_CLIENT_SECRET",
                    "refresh_token": "GOOGLE_REFRESH_TOKEN",
                },
            },
        )

        cls.client = McpTestClient("google-tasks", make_uv_command("google-tasks"))
        cls.client.start()
        cls._created_task_id = None

    @classmethod
    def tearDownClass(cls):
        if cls._created_task_id:
            try:
                tools = cls.client.list_tools()
                tool_names = [t["name"] for t in tools]
                delete_tool = next(
                    (n for n in tool_names if "delete" in n.lower()),
                    None,
                )
                if delete_tool:
                    cls.client.call_tool(delete_tool, {
                        "task_id": cls._created_task_id,
                    }, timeout=15)
            except Exception:
                pass
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0)

    def test_list_task_lists(self):
        """Read-only: list task lists."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        list_tool = next(
            (n for n in tool_names if "list" in n.lower()),
            tool_names[0],
        )
        result = self.client.call_tool(list_tool, {}, timeout=30)
        self.assertIn("result", result, f"List failed: {result}")

    def test_create_and_delete_task(self):
        """Write test: create a test task, then delete it."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        create_tool = next(
            (n for n in tool_names if "create" in n.lower() or "add" in n.lower()),
            None,
        )
        if create_tool is None:
            self.skipTest(f"No task creation tool found in: {tool_names}")

        import time
        result = self.client.call_tool(create_tool, {
            "title": f"_mcp_integration_test_{int(time.time())}",
        }, timeout=30)
        self.assertIn("result", result, f"Create failed: {result}")
```

- [ ] **Step 2: Run test**

Run: `uv run python -m pytest tests/integration/test_google_tasks_mcp.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_google_tasks_mcp.py
git commit -m "test: add Google Tasks MCP live integration test"
```

### Task 15: Google Docs (with subtabs) integration test

**Files:**
- Create: `tests/integration/test_google_docs_mcp.py`

- [ ] **Step 1: Write test**

```python
# tests/integration/test_google_docs_mcp.py
"""Live integration test for Google Docs (with subtabs) MCP server."""

import unittest

from tests.integration.conftest import McpTestClient, make_uv_command, MCP_SERVERS_DIR


class TestGoogleDocsMcp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0, str(MCP_SERVERS_DIR))
        from lib.env_loader import resolve_credentials

        resolve_credentials(
            source="env_file",
            config={
                "base_dir": MCP_SERVERS_DIR / "google-docs-with-subtabs",
                "required": ["GDOCS_QUOTA_PROJECT"],
            },
        )

        cls.client = McpTestClient(
            "google-docs-with-subtabs",
            make_uv_command("google-docs-with-subtabs"),
        )
        cls.client.start()
        cls._created_doc_id = None

    @classmethod
    def tearDownClass(cls):
        if cls._created_doc_id:
            try:
                tools = cls.client.list_tools()
                tool_names = [t["name"] for t in tools]
                delete_tool = next(
                    (n for n in tool_names if "delete" in n.lower()),
                    None,
                )
                if delete_tool:
                    cls.client.call_tool(delete_tool, {
                        "doc_id": cls._created_doc_id,
                    }, timeout=15)
            except Exception:
                pass
        cls.client.stop()

    def test_server_lists_tools(self):
        tools = self.client.list_tools()
        self.assertGreater(len(tools), 0)

    def test_list_docs(self):
        """Read-only: list recent docs."""
        tools = self.client.list_tools()
        tool_names = [t["name"] for t in tools]

        list_tool = next(
            (n for n in tool_names if "list" in n.lower() or "search" in n.lower()),
            tool_names[0],
        )
        result = self.client.call_tool(list_tool, {}, timeout=30)
        self.assertIn("result", result, f"List failed: {result}")
```

- [ ] **Step 2: Run test**

Run: `uv run python -m pytest tests/integration/test_google_docs_mcp.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_google_docs_mcp.py
git commit -m "test: add Google Docs MCP live integration test"
```

---

## Chunk 5: Makefile & Final Validation

### Task 16: Add test-integration Makefile target

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Add target to Makefile**

Add after the existing `test` target (around line 123):

```makefile
test-integration: ## Run live MCP integration tests
	@uv run python -m pytest tests/integration/ -v --tb=short
```

Also add `test-integration` to the `.PHONY` list at line 14.

- [ ] **Step 2: Verify target works**

Run: `make test-integration`
Expected: All integration tests run and pass

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add make test-integration target for MCP live tests"
```

### Task 17: Run full test suite

- [ ] **Step 1: Run make verify (existing tests)**

Run: `make verify`
Expected: All pass — no regressions

- [ ] **Step 2: Run make test-integration (new tests)**

Run: `make test-integration`
Expected: All 7 server test modules pass

- [ ] **Step 3: Final commit if any cleanup needed**

```bash
git add -u
git commit -m "chore: final cleanup for MCP integration tests"
```

---

## Dependency Order

```
Task 1 (env_file resolver)
  → Task 2 (UC resolver)
  → Task 3 (gcloud ADC resolver)
    → Task 4 (dispatcher)
      → Task 5 (UC wrappers)
      → Task 6 (gcloud + env_file wrappers)  [parallel with Task 5]
        → Task 7 (regression check)
          → Task 8 (test infra)
            → Tasks 9-15 (per-server tests)  [all parallel]
              → Task 16 (Makefile)
                → Task 17 (final validation)
```
