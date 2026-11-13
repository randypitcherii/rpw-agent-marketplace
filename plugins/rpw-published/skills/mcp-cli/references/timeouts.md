# Timeouts (#2429, #2623)

The MCP Inspector CLI and its fixed 60s `tools/call` ceiling are gone. A call now goes
to a `mcporter serve --stdio` child, the same path the plugin's `rpw` MCP entry uses,
and the CLI's own deadline is **120s** (`--timeout SECONDS`, or
`RPW_MCP_CALL_TIMEOUT_SECONDS`). Inside it, mcporter 0.16.0's `serve` holds one tool
call to 60s (it passes no timeout to its daemon; ADR-2026-10-28).

That is deliberately above every server-side limit: each rpw tool answers inside
about 45s, and a slow upstream returns a structured envelope instead of hanging
(`upstream_timeout` with `retryable` and `retry_after_seconds`, `rate_limited`, or
`side_effect_unknown` for a write whose outcome is unclear). Retry the first two as
told; for `side_effect_unknown`, verify before retrying. `glean_chat` returns a
`handle` when the answer is not ready; resolve it with `glean_chat_result`.

A server's first start after a plugin update can include a one-time `uv sync`;
`tools` allows 180s for that.
