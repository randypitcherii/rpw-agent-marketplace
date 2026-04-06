---
name: versioning_standards
description: Use when setting up versioning for a project, comparing versions between components, or implementing version checks. Enforces git-hash-based versioning standard across all projects.
version: 1.0.0
---

# Versioning Standard: Git-Hash Versioning

## Canonical Version Identifier

Every deployable component MUST expose a version composed of:
- **git short hash** (7-char): primary identifier for build comparison
- **commit date** (YYYY-MM-DD): human-readable timestamp
- **semver** (X.Y.Z): decorative, for release management only

Display format: `v{semver} · {hash} · {date}` (e.g., `v1.0.0 · 350625c · 2026-03-09`)

## Rules

1. **One semver source per component**
   - JavaScript/TypeScript: `package.json` `version` field
   - Python: `pyproject.toml` `[project].version` field
   - Other: a single `VERSION` file at the project root

2. **Runtime git info resolution**
   - Resolve at startup, cache for the process lifetime
   - Use `git rev-parse --short HEAD` for hash
   - Use `git log -1 --format=%as` for commit date (YYYY-MM-DD)
   - Always wrap in try/catch — git may not be available in production builds

3. **Security: no shell injection**
   - Python: `subprocess.run(['git', ...])` — never `os.popen()` or `subprocess.run(shell=True)`
   - TypeScript: `execFileSync('git', [...])` — never `execSync('git ...')`
   - Always set a timeout (1-3 seconds)

4. **Multi-component version comparison**
   - Compare git hashes only (semver is decorative and unreliable for drift detection)
   - Expose hash + date in health/status endpoints
   - Treat unknown/empty hash as compatible (graceful degradation for non-git builds)
   - Never hardcode fallback versions that match real versions (use `"unknown"`, never `"0.1.0"`)

5. **Health endpoint schema** (for services)
   ```json
   {
     "version": "1.0.0",
     "git_hash": "350625c",
     "git_commit_date": "2026-03-09"
   }
   ```

## Reference Implementations

### Python (proxy/server)
```python
import subprocess
from pathlib import Path
from typing import Optional

_git_info_cache: Optional[tuple] = None

def get_git_info() -> tuple[Optional[str], Optional[str]]:
    """Return (short_hash, commit_date), cached after first call."""
    global _git_info_cache
    if _git_info_cache is not None:
        return _git_info_cache

    for cwd in [Path(__file__).parent, Path.cwd()]:
        try:
            hash_r = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True, text=True, timeout=1, cwd=str(cwd))
            date_r = subprocess.run(
                ['git', 'log', '-1', '--format=%as'],
                capture_output=True, text=True, timeout=1, cwd=str(cwd))
            if hash_r.returncode == 0:
                h = hash_r.stdout.strip()
                d = date_r.stdout.strip() if date_r.returncode == 0 else None
                _git_info_cache = (h, d)
                return _git_info_cache
        except Exception:
            continue

    _git_info_cache = (None, None)
    return _git_info_cache
```

### TypeScript (extension/client)
```typescript
import { execFileSync } from "child_process";

function resolveGitInfo(): { hash?: string; date?: string } {
  try {
    const hash = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
      encoding: "utf8", timeout: 3000,
    }).trim();
    let date: string | undefined;
    try {
      date = execFileSync("git", ["log", "-1", "--format=%as"], {
        encoding: "utf8", timeout: 3000,
      }).trim();
    } catch { /* date is optional */ }
    return { hash, date };
  } catch {
    return {};
  }
}

const gitInfo = resolveGitInfo();
export const GIT_HASH = gitInfo.hash;
export const GIT_DATE = gitInfo.date;
```

### Version Comparison
```typescript
export function versionsMatch(
  localHash: string | undefined,
  remoteHash: string | undefined,
): boolean {
  if (!localHash?.trim() || !remoteHash?.trim()) return true;
  return localHash.trim() === remoteHash.trim();
}
```
