# Interactive engineer-facing maps

The Brief workflow answers one question in a static PNG. Use
[Archify](https://github.com/tt-a1i/archify) when the artifact itself must be an
engineering tool.

## Routing boundary

Route to Archify when engineers need at least one of these capabilities:

- search nodes or filter a dense system;
- trace upstream/downstream reach or an exact route;
- open revision-pinned source references;
- compare architecture snapshots as Before / Delta / After;
- step through a guided story, sequence, workflow, data flow, or lifecycle.

Do not route merely because the request says “architecture.” A non-technical explanation,
Slack image, document figure, or deck slide stays in Brief. If one request needs both,
produce two artifacts: the Archify map for exploration and a separately edited Brief PNG
for communication.

## Archify contract

Archify compiles typed JSON IR into a validated, self-contained interactive HTML viewer.
Its supported map types are architecture, workflow, sequence, dataflow, and lifecycle.
The JSON is the source; HTML is the primary artifact; PNG/SVG/WebM are exports.

Use Archify's own schemas, examples, validators, and delivery command. Do not apply
Brief's DOM-specific `qa.sh` to its viewer. In an existing reviewed Archify checkout, the
bounded flow is:

```bash
ARCHIFY_UPDATE_CHECK_DISABLED=1 node bin/archify.mjs validate <type> <map.json> \
  --quality showcase --json
ARCHIFY_UPDATE_CHECK_DISABLED=1 node bin/archify.mjs deliver <type> <map.json> \
  <map.html> --quality showcase --json
```

Require both commands' machine-readable validation to pass, then open the HTML and test
the interactions the request depends on. Export a static image only as supporting
evidence; it cannot prove search, tracing, source links, or guided navigation.

Archify is external software, not vendored by this marketplace. Do not clone, install, or
execute it without the user's approval and a review appropriate to the environment. If it
is unavailable, report that prerequisite; do not silently fall back to a static Brief
artifact when interaction is required.
