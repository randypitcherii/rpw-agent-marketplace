# chrome-devtools MCP Server

Wraps the `chrome-devtools-mcp` npm package, which provides browser automation capabilities through Chrome DevTools Protocol.

## Capabilities

- Navigate, click, fill forms, take screenshots
- Evaluate JavaScript in-page
- Monitor console messages and network requests
- Run Lighthouse audits and performance traces
- Emulate devices and viewports

## Configuration

No secrets or environment variables required. All configuration is passed via CLI args.

Default settings:
- **User data dir**: `/tmp/mcp-chrome-user-data`
- **Emulation**: Responsive
- **Viewport**: 1920x1080

## Usage

**Direct execution:**
```bash
./run_mcp.sh
```

**MCP client config:** Merge `chrome-devtools.mcp.json` into your MCP client configuration.
