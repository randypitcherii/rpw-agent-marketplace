# Composing calls through rpw-mcp-cli

## File-valued string arguments

Put a long or quote-heavy string argument in a file rather than in `--json`, using
`--arg-file KEY=PATH` (repeatable). A markdown body or a Slack message then never has
to survive shell quoting. `--json` defaults to `{}`. A key may come from one source or
the other, not both. This is an explicit flag, with no `@path` magic, because a real
string argument may itself start with `@`.

```bash
rpw mcp call google-docs gdocs_create --json '{"title":"Q3 notes"}' \
  --arg-file content=body.md
```

## Reading the result

`call` prints the full MCP result under `.result`: every content block,
`structuredContent` and `isError`. A FastMCP tool's own JSON arrives as a string at
`.result.structuredContent.result`, so it takes two `jq` passes. `tools` prints the
tool list at `.result.tools[]`. Use `--full` inside a pipeline so a large result is
never swapped for a preview.

## Chaining calls in one shell call

Each warm call takes about a second. One shell call that chains N operations still
replaces N model turns, and it keeps the intermediate payloads out of context:

```bash
rpw mcp --full call google-docs gdocs_list | jq -r '.result.structuredContent.result' \
  | jq -r '.files[].id' | while read -r id; do
    rpw mcp --full call google-docs gdocs_read --json "{\"doc_id\":\"$id\"}" \
      | jq -r '.result.structuredContent.result' | jq -r '.title'
  done
```

For a single operation, a native MCP tool (when the harness has one) is faster.
