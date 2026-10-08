# Model selection for dispatched work — OSS first, frontier where it counts (#915)

Companion to [SKILL.md](SKILL.md) section 4. Read this when picking the model for
**delegated** work. It does not govern the model an interactive session runs on.

## The problem it fixes

In a reviewed sample, most dispatched sessions used frontier models at high
reasoning effort — including work with no judgment content at all: filing issues
from a prepared list, reading session logs, and polling a deployment. Frontier models were
the default because nothing said otherwise.

## The rubric — one question

> **Does this task require judgment that a review step cannot recover?**
>
> - **No → route it to an OSS model.** Mechanical, high-volume, read-heavy,
>   template-shaped work: metadata edits across N issues, reading logs and
>   transcripts, renames, boilerplate from a template, polling a run, turning a
>   prepared list into artifacts.
> - **Yes → keep it on a frontier model.** Orchestration and decomposition,
>   architecture and trade-off calls, security verdicts, the final review pass,
>   and anything where a wrong answer is *plausible* rather than *detectably
>   wrong*.

The asymmetry is the whole rule. A mechanical task's output has a ground-truth
check — [`return-verification.md`](return-verification.md) — so if the OSS model
gets it wrong you find out and the retry is cheap. A judgment call has no such
check: a confidently wrong architectural recommendation reads exactly like a
right one. There you are paying for error *avoidance*, not error *detection*.

**Corollary: routing to OSS raises the value of the section-6 verification step,
it never lowers it.** An OSS dispatch claiming a durable artifact gets the same
check, run the same way, with the same "unverified is not done" reporting rule.

## Choose from the live model inventory

Use a capable OSS coding model from the current workspace inventory for mechanical work. Do not hard-code a model name from this page: availability, aliases, and capabilities change. The rubric above is the durable part.

List what your workspace actually serves:

- `ucode status` — current workspace, tool configs, and saved model selections.
- `ucode --dry-run` — prints the config files `configure` *would* write, without
  writing them. The read-only way to see which model is pinned.
- `ucode configure` — discovers the models the workspace's AI Gateway advertises
  and writes them into each agent's config ("freshly discovered models"). This one
  **mutates local config**, so it is not a probe.
- `databricks serving-endpoints list` — the endpoints the workspace serves.

The selected model is a **config-level** choice that `ucode configure` records — not a per-launch flag, as the next section explains.

## The invocation

`ucode` (`github.com/databricks/ucode`) configures and launches coding agents
through the Databricks AI Gateway. **Model pinning is what `ucode configure`
writes** — there is no per-launch model flag to pass:

```sh
ucode configure                              # discovers the workspace's models, pins them per agent
ucode claude                                 # launch on the pinned model — this is the verified path
ucode claude --provider <catalog.schema.name> # optional override for a verified provider
```

Do not assume a `--model` flag exists. Run `ucode claude --help` on the installed version before constructing a command. Commonly advertised options include:

| Flag | What it does |
|---|---|
| `--provider <catalog>.<schema>.<name>` | Route through a Unity Catalog Model Provider Service. Skips Databricks model pinning; pass before any `--` separator. |
| `--workspace <url>` | Workspace to launch against; sets up and authenticates it if needed. |
| `--skip-preflight` | Trust a prior `ucode configure`; skip per-launch auth + AI Gateway re-validation. |
| `--enable-smart-routing` / `--disable-smart-routing` | AI Gateway model routing for Claude Code sessions and subagents. |

Verify both the `--provider` flag and its value against the installed version and live workspace. Do not infer that every fully qualified model id is a Model Provider Service.

Practical consequence: **pin with `ucode configure` and launch bare `ucode claude`**
(the workspace config decides the model), and reach for `--provider` only if you
have a real Model Provider Service to route through. Either way, run
`ucode claude --help` on your own version first — the flag set above is one
version's, not a stable contract.

## Preconditions — check `PATH` before you dispatch

```sh
command -v ucode        # → /Users/<you>/.local/bin/ucode ; empty means not installed
ucode claude --help     # → the flags your version actually accepts
```

Both are read-only and cost a second. If `command -v` prints nothing, `ucode` is
not on `PATH` and the dispatch dies at launch with a shell `command not found` —
**that failure is an install problem, not an OSS model underperforming.** Install
it, or add `~/.local/bin` to `PATH`, before you route work there.

Apply the same precondition to every native model harness. If its CLI is not on `PATH`, installing it is a separate task; do not interpret a launch failure as poor model performance.

## Out of scope

Changing the model an *interactive* session runs on, wiring the `qwen`/`kimi`
CLIs, fixing omnigent's native-harness path, and any cost measurement or
reporting infrastructure. This page is about where delegated work runs.
