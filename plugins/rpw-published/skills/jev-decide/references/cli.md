# jev_decide.py reference

`uv run --no-project python scripts/jev_decide.py <command> --help` is authoritative. This page
covers the parts `--help` cannot.

## Commands

| Command | Does |
|---|---|
| `ask` | One state and a question set → answers. The questions come from `--questions FILE` and/or repeatable inline flags: `--noul ID=TEXT`, `--choice ID=TEXT:a\|b\|c`, `--score ID=TEXT:low\|mid\|high`. The state is `--state TEXT` or `--state-file PATH\|-`. JSON input is sent as structure; anything else is sent as text. |
| `session` | Omnigent session records → one action each ([omnigent-sessions.md](omnigent-sessions.md)). `--input` repeats and accepts `-` for stdin. |
| `eval` | Labeled JSONL → per-question metrics. A case is `{"state": …, "labels": {qid: expected}}`. With `--preset omnigent-session` it is `{"session": {…}, "labels": {…}, "action": "…", "now": epoch}` and the report adds `action_accuracy`. |
| `models` | Lists System One models. Through an rpw LLM proxy it covers the whole pool, with the workspaces serving each; direct (`--profile`) it covers that one workspace. |
| `doctor` | Prints the resolved endpoint and makes one tiny live call. |
| `questions` | Prints the built-in `omnigent-session` question set. |

## Transport

The first that resolves wins:

1. `--base-url URL` or `JEV_DECIDE_BASE_URL`, sent with no auth. Use this for a local LLM proxy.
2. `--profile NAME`, direct to the workspace. The host comes from `~/.databrickscfg` and the
   token from `databricks auth token -p NAME`.
3. An rpw LLM proxy recorded in `~/.rpw/ports.json` (`llm-proxy.listener.<RPW_LLM_PROXY_ENV or prod>`).
   If it is not running, the next candidate is tried.
4. `DATABRICKS_HOST` + `DATABRICKS_TOKEN`.
5. The `DEFAULT` CLI profile.

## Model selection

`--model` or `JEV_DECIDE_MODEL` takes one of three forms:

| Value | Resolves to |
|---|---|
| `auto` (default) | The newest TypeSafe Jev that discovery finds, else OpenJev, else `system.ai.openjev-qwen35-4b` when discovery fails. The JSON says which, under `model_selection`. |
| a short name (`jev`, `openjev`) | Matched against discovery: exact last segment, then a whole hyphen token, then a unique substring. `jev` never matches `openjev`. |
| `catalog.schema.model` | Sent as-is, with no discovery call. |

The route accepts only the UC model-service name: `databricks-X` becomes `system.ai.X`. Two
names that look right fail:
- The serving-endpoint name (`databricks-openjev-…`) gets a 400.
- OpenJev's `foundation_model.name` (`system.ai.databricks-openjev-…`) gets a 404.

Discovery derives the name from the endpoint name for that reason. Responses report a
backend id (`jev-1.14.0`) that is not callable either, so the output's `model` is the name
that was sent.

Not every workspace serves both models, which is why `auto` relies on discovery.

Measured 2026-10-19:
- **On 8 labeled Omnigent sessions**, Jev got 8/8 actions vs OpenJev's 7/8. Its phase
  coverage was 0.88 vs 0.50, its Brier score was lower on every question, and its median
  latency was 521 ms vs 769 ms.
- **Jev emits about 350 output tokens per call**; OpenJev emits none.

## Output

JSON by default, `--compact` for one line, `--format text` for humans. Each answer has:

| Key | Meaning |
|---|---|
| `answer` | The label (`true`/`false` for noul), or `"unsure"` |
| `best_guess` | The label even when unsure |
| `confidence` | The best label's probability |
| `probabilities` | The full distribution, keyed by label (score levels by **label**, not index) |
| `p_true` / `score` | noul probability / score expected level (0-based) |
| `order_agreement` | Present when both option orders were asked |
| `unsure_reason` | Why it abstained |

`abstain_below` on a question in a set file overrides `--threshold` for that question. It is
stripped before the request, because the route returns 422 for any field it does not know.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | ok (`unsure` answers included) |
| 2 | usage error, or the route rejected the request (400/404/422) |
| 3 | transport or auth (`auth_expired` carries the `databricks auth login` hint) |
| 4 | the response was missing an answer or unparseable |
| 10 | `--fail-on-unsure` and at least one answer was unsure |

Failures print `{"ok": false, "error": {"code", "message", "hint"}}` to stdout, never a
traceback. With code 10 you can use `ask` as a shell gate:

```bash
uv run --no-project python "$J" ask --state-file pr.json --fail-on-unsure \
  --noul 'ready=Does this PR description state the problem, the change, and how it was tested?'
```

`--log FILE` appends every decision, **with its state**, as JSONL. The file is local and
yours. Label a sample of it to grow an eval set.
