---
name: python-with-uv
description: Use when setting up Python projects, installing packages, running Python scripts, or managing dependencies - enforces UV package manager workflow with automatic virtual environment handling, replacing pip and manual venv management
---

# Python Development with UV

## Overview

All Python work on this system uses the `uv` package manager exclusively. UV handles virtual environments automatically - no manual activation, no pip, no confusion.

**Core principle:** UV replaces both pip and manual venv management. One tool, zero friction.

## When to Use

Use this workflow when:
- Setting up a new Python project
- Installing Python packages
- Running Python scripts or commands
- Managing project dependencies
- Working with virtual environments

**Do NOT use for:**
- Non-Python projects
- System Python packages (use system package manager)

## Quick Reference

| Task | Command | Notes |
|------|---------|-------|
| Initialize project | `uv init --bare && uv venv --seed --prompt " 🌞 "` | Sets up bare project with seeded venv |
| Add dependency | `uv add <package> && uv sync` | Always sync after adding |
| Remove dependency | `uv remove <package> && uv sync` | Always sync after removing |
| Run Python script | `uv run python script.py` | No venv activation needed |
| Run any command | `uv run <command>` | Runs in project's venv context |
| Install all deps | `uv sync` | Syncs pyproject.toml to venv |
| Update dependencies | `uv lock --upgrade` | Updates lock file |

## Core Rules

### ✅ ALWAYS

- Use `uv` for ALL Python operations
- Run commands with `uv run` prefix
- Sync after adding/removing packages: `uv add pkg && uv sync`
- Work from correct project directory (UV is directory-aware)

### ❌ NEVER

- Use `pip` or `pip3` (blocked in permissions)
- Run `python` or `python3` directly (blocked in permissions)
- Manually activate virtual environments (`source venv/bin/activate`)
- Use `virtualenv` or `venv` commands

## Common Mistakes

| Mistake | Why It's Wrong | Correct Approach |
|---------|----------------|------------------|
| `pip install requests` | Uses pip instead of uv | `uv add requests && uv sync` |
| `python script.py` | Bypasses UV's venv handling | `uv run python script.py` |
| `uv add pandas` (without sync) | Dependencies not installed | `uv add pandas && uv sync` |
| `source .venv/bin/activate` | Manual venv management unnecessary | Just use `uv run` |
| Running from wrong directory | UV can't find pyproject.toml | `cd` to project root first |

## Working Directory Requirement

UV requires you to be in the correct project directory because it looks for `pyproject.toml`:

```bash
# ❌ Wrong - not in project directory
cd ~
uv run python my_project/script.py  # Won't find pyproject.toml

# ✅ Correct - in project directory
cd ~/my_project
uv run python script.py  # Finds pyproject.toml
```

## Workflow Examples

### Starting a New Project

```bash
# Navigate to projects directory
cd ~/projects/my-new-project

# Initialize with bare template and seeded venv
uv init --bare && uv venv --seed --prompt " 🌞 "

# Add dependencies
uv add pandas numpy && uv sync

# Create and run script
uv run python analyze.py
```

### Adding Packages to Existing Project

```bash
# Navigate to project
cd ~/projects/my-project

# Add package and sync in one command
uv add requests && uv sync

# Verify it works
uv run python -c "import requests; print(requests.__version__)"
```

### Running Scripts

```bash
# Simple script execution
uv run python main.py

# Script with arguments
uv run python process.py --input data.csv --output results.json

# Interactive Python shell with project dependencies
uv run python
```

## Red Flags - STOP and Use UV Instead

If you catch yourself about to:
- Type `pip install`
- Run `python` directly
- Create/activate a virtualenv manually
- Wonder "which Python am I using?"

**STOP.** Use UV commands instead.

## Benefits Over pip/venv

- **No activation needed:** `uv run` handles venv automatically
- **Faster installs:** UV is written in Rust, significantly faster than pip
- **Simpler workflow:** One tool instead of pip + venv + virtualenv
- **Better dependency resolution:** UV has superior conflict resolution
- **Lockfile support:** Reproducible environments via uv.lock

## Troubleshooting

**"Command not found: uv"**
- UV not installed. Install with: `brew install uv`

**"No pyproject.toml found"**
- Not in project directory. Run `cd` to project root or initialize with `uv init --bare`.

**"Package not found after uv add"**
- Forgot to sync. Always use: `uv add package && uv sync`

**"Wrong Python version"**
- UV uses Python from pyproject.toml. Specify version: `uv python pin 3.11`
