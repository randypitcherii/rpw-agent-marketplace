#!/usr/bin/env bash
# Thin wrapper for chrome-devtools-mcp.
# No secrets needed — all config is via CLI args.
exec npx chrome-devtools-mcp@latest \
  "--userDataDir=$HOME/.vibe/chrome/profile" \
  --no-category-performance \
  --no-category-emulation
