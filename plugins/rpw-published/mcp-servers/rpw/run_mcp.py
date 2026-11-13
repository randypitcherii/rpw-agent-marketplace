#!/usr/bin/env python3
"""The `rpw` MCP server: the one MCP entry across the rpw plugins (#2215, #2623).

A thin front over the mcporter keep-alive runtime. See front.py for the behavior and
mcp_runtime.py for how the installed plugins become one mcporter config.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import front  # noqa: E402


def main() -> None:
    # The plugin root is this file's own location, two levels up, never
    # CLAUDE_PLUGIN_ROOT: an inherited value could name a different plugin, and a uvx
    # install has no such variable at all.
    front.run(HERE.parent.parent)


if __name__ == "__main__":
    main()
