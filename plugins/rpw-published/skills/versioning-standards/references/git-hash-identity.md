# Git-hash build identity — reference implementations

Companion to `SKILL.md` §5. Copy the shape, not the file: each snippet resolves git info once,
caches it for the process lifetime, uses argv-list subprocess calls with a timeout, and degrades
to unknown rather than raising at startup.

**Python (proxy/server)**
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

**TypeScript (extension/client)**
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

**Version comparison** — hashes only, unknown is compatible:
```typescript
export function versionsMatch(
  localHash: string | undefined,
  remoteHash: string | undefined,
): boolean {
  if (!localHash?.trim() || !remoteHash?.trim()) return true;
  return localHash.trim() === remoteHash.trim();
}
```
