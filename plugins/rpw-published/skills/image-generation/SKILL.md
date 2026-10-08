---
name: image-generation
description: Generate one image or a batch of image variations with the Gemini image tool, save them to a requested folder, and verify the files and visible result. Use for "generate images", "image variations", "make cover art", "Notion-style covers", "page cover images", or abstract/art-direction batches. Runs batches as parallel background work so the main agent stays responsive. NOT for data charts (use dataviz) or architecture diagrams (use diagram).
---

# Image generation

Create image artifacts with the marketplace's `gemini-image` MCP server. For batches,
turn one direction into distinct prompts, launch them concurrently in the background, and
return control to the user while generation continues.

## Route the request

- Generated art, cover images, visual variations, or edits → this skill.
- Data-driven chart, plot, or dashboard → the `dataviz` skill.
- Concept or architecture diagram → the `diagram` skill.
- Existing image plus a requested change → use `edit_image`; do not regenerate from scratch.

Resolve an explicit destination to an absolute path before generation. If the user says
"Desktop," use the current user's Desktop; never guess another user's home directory.
Create one descriptive folder for a batch and use stable numbered names such as
`abstract-cover-01.png`.

## Discover before calling

Use a native MCP client when the harness exposes one. Otherwise load the `mcp-cli` skill,
resolve its `rpw-mcp-cli`, and follow **servers → tools → call**:

```bash
"$MCP_CLI" servers
"$MCP_CLI" tools rpw-published:gemini-image
```

Never guess the server name, tool name, model, or arguments. Read the live schema first.
The expected generation tool is `generate_image`; its current result names the temporary
file it wrote. Model aliases and aspect-ratio choices can change, so the schema wins over
examples in this skill.

## Build variations without dropping constraints

Write a shared base prompt for composition, medium, intended use, aspect ratio, and hard
exclusions. Then add one deliberate variation axis per output: palette, geometry, lighting,
texture, depth, or motion. Every result must be meaningfully different, not the same prompt
with a number changed.

Repeat every hard user constraint in **every variation prompt**. Do not rely on constraints
appearing only in the base instructions visible to the agent. For example, a request for
abstract covers with no people and no text should restate: no people, faces, figures,
letters, typography, logos, symbols, or text of any kind. Treat exclusions as acceptance
criteria, not suggestions.

For page covers, use the widest supported aspect ratio, spread visual energy across the
canvas, and avoid a single fragile focal point that center cropping could remove.

## Keep batch generation non-blocking

**Hard rule:** launch batch calls as **parallel background** work with **bounded fan-out**
(default 5 concurrent calls). The main agent remains responsive after launch. Do not wait
for all image calls inside the same foreground tool invocation, and do not make ten slow
calls sequentially.

Preferred order:

1. Use the harness's async/background tool-call facility, if it can run MCP calls.
2. In a shell-only harness, start detached `rpw-mcp-cli` processes with unique JSON,
   stdout, stderr, and PID files.
3. Return control after launch. Poll completion in later short calls or on the next user
   turn; start the next batch only when capacity is available.

Shell pattern after schema discovery (illustrative; use the live arguments):

```bash
RUN_DIR="$(mktemp -d /tmp/image-batch.XXXXXX)"
for i in 01 02 03 04 05; do
  payload="$RUN_DIR/$i.request.json"       # write one complete prompt per file
  nohup "$MCP_CLI" call rpw-published:gemini-image generate_image \
    --json "$(cat "$payload")" \
    >"$RUN_DIR/$i.result.json" 2>"$RUN_DIR/$i.stderr" </dev/null &
  echo $! >"$RUN_DIR/$i.pid"
done
printf '%s\n' "$RUN_DIR"                  # persist this path for later polling
```

Do not put an unquoted user prompt directly into shell syntax. Build request JSON with
`jq --arg` or write it with a JSON library. Unique filenames are mandatory because the
MCP server writes generated files to a temporary directory.

Poll without blocking:

```bash
for pid_file in "$RUN_DIR"/*.pid; do
  pid="$(cat "$pid_file")"
  kill -0 "$pid" 2>/dev/null && echo "running $pid" || echo "finished $pid"
done
```

A stopped PID is not proof of success. Parse each result, confirm it is not an MCP error,
and locate the generated file. Retry only failed variations, once, preserving their intended
variation and all hard constraints. If failures are systemic (authentication, quota, model
access), stop the batch and report the exact remediation instead of retrying every item.

## Collect and verify

Copy successful temporary outputs into the destination only after each result parses as a
success. Do not report completion until all requested artifacts pass:

- **File count:** exactly the requested number of non-empty output files.
- **Type:** magic bytes identify the expected image format; an extension alone is not proof.
- **Dimensions:** each image has the intended supported aspect ratio and consistent size.
- **Visual QA:** visually inspect every output through the harness's image reader. Check
  composition, crop safety, meaningful variation, and every exclusion such as no people or
  no text.
- **Naming:** stable numbered filenames with no accidental overwrites.

Delete corrupt or partial destination files. Keep diagnostic result/stderr files in the run
directory until verification finishes, then remove the run directory unless debugging is
still needed.

Report the absolute destination folder, image count, format, and dimensions. If generation
is still running, say so plainly and give the run directory or progress count; responsiveness
must never be purchased by pretending unfinished files are done.
