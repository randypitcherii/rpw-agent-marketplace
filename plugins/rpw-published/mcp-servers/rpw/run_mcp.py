#!/usr/bin/env python3
"""The `rpw` MCP server: one entry in this plugin's .mcp.json, fronting servers.json (#2215).

See lib/aggregator.py for the behavior: parallel startup, a failed backend is dropped
rather than fatal, sessions stay open, tool names are not prefixed.
"""

import sys
from pathlib import Path

# The shared lib is not a distributed package; servers put mcp-servers/ on the path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import aggregator  # noqa: E402


def main() -> None:
    aggregator.run("rpw", Path(__file__).resolve().parent)


if __name__ == "__main__":
    main()
