"""Shared test fixtures for the rpw-agent-marketplace test suite."""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"


@pytest.fixture
def load_script_module():
    """Return a loader that imports a script from the scripts/ directory by name.

    Usage::

        def test_something(load_script_module):
            mod = load_script_module("bump_marketplace_versions")
            mod.some_function()
    """

    def _loader(script_name: str):
        module_path = SCRIPTS_DIR / f"{script_name}.py"
        spec = importlib.util.spec_from_file_location(script_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Failed to load module spec from {module_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _loader


@pytest.fixture
def temp_json_file():
    """Yield a (tmp_dir_path, write_helper) tuple for temp directory/file setup.

    The write_helper accepts a relative filename and text content, writes it,
    and returns the Path to the created file.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        def _write(name: str, content: str = "") -> Path:
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return p

        yield root, _write
