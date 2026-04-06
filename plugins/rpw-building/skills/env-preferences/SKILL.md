---
name: env-preferences
description: Reusable APP_ENV env-file pattern for local development. Commit template.env, keep dev/test/prod env files local-only, and load the selected file at app startup.
version: 1.0.0
---

# Env Preferences

Use this skill when you are setting up environment-variable conventions for a new project or runtime entrypoint.

## Standard Pattern

1. Commit `template.env` with placeholders and comments.
2. Keep `dev.env`, `test.env`, and `prod.env` local-only (never committed).
3. Select runtime environment with `APP_ENV=dev|test|prod` (default: `dev`).
4. App startup should load `<APP_ENV>.env`, validate required keys, and fail with a clear error if the file is missing.

## Required `.gitignore` Entries

```text
dev.env
test.env
prod.env
**/dev.env
**/test.env
**/prod.env
```

## Startup Pattern (Python)

```python
import os
from pathlib import Path
from dotenv import load_dotenv

valid = {"dev", "test", "prod"}
app_env = os.getenv("APP_ENV", "dev").strip().lower()
if app_env not in valid:
    raise ValueError(f"Invalid APP_ENV '{app_env}'")

env_path = Path(__file__).parent / f"{app_env}.env"
if not env_path.exists():
    raise FileNotFoundError(f"Missing {env_path}; copy template.env first")

load_dotenv(env_path)
```

## Documentation Checklist

- README setup tells users to copy `template.env` into `dev.env`/`test.env`/`prod.env`.
- README run section includes `APP_ENV=test ...` and `APP_ENV=prod ...` examples.
- Startup script docstring explains the APP_ENV loading behavior.
