# Composing calls through rpw-mcp-cli

## File-valued string arguments

Put a long or quote-heavy string argument in a file rather than in `--json`, using
`--arg-file KEY=PATH` (repeatable). A markdown body or a Slack message then never has
to survive shell quoting. `--json` defaults to `{}`. A key may come from one source or
the other, not both. This is an explicit flag, with no `@path` magic, because a real
string argument may itself start with `@`.

```bash
"$MCP_CLI" call google-docs gdocs_create --json '{"title":"Q3 notes"}' \
  --arg-file content=body.md
```

## Unwrapping the result

A tool's own JSON arrives as a string at `.result.structuredContent.result`, so it
takes two `jq` passes. Use `--full` inside a pipeline so a large result is never
swapped for a preview.

## Chaining calls in one shell call

Each call is a cold process taking several seconds. One shell call that chains N
operations still replaces N model turns, and it keeps the intermediate payloads out of
context:

```bash
"$MCP_CLI" --full call google-docs gdocs_list | jq -r '.result.structuredContent.result' \
  | jq -r '.files[].id' | while read -r id; do
    "$MCP_CLI" --full call google-docs gdocs_read --json "{\"doc_id\":\"$id\"}" \
      | jq -r '.result.structuredContent.result' | jq -r '.title'
  done
```

For a single operation, a native MCP tool (when the harness has one) is faster.
