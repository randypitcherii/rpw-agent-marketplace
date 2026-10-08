# Trace-SQL harvest — the analysis path

Companion to `SKILL.md`. Replaces run-centric comparison entirely: one SQL statement over the
UC trace tables, then paired per-task ratios in ~80 lines of Python.

## Why runs are the wrong unit

Every infra failure fragments MLflow runs — expired auth, a 429 rerun, a wedged segment resumed
under the same baseline id. Run-level aggregates and per-run artifacts then describe *a segment*,
not a sweep. A comparison tool that picks "the newest run per (arm, sweep)" and reads its artifact
silently compares whatever segment finished last (once: a single-task segment). That is
structural, not a bug — the data model contradicts how the runs actually get produced.

Worse, per-trial records write **0 tokens for an errored trial** while that trial burned real
tokens (one recursion-capped trial: 916k input, 92% cache-read). Any token comparison built on
trial records therefore *rewards* the arm that loops.

Traces have neither problem: one row per trial, tokens recorded on errored trials, immune to how
the runs were sliced.

## The query

Two tables, joined on `trace_id`:

- `<catalog>.<schema>.<prefix>_trace_metadata` — token usage + `mlflow.sourceRun` (the tag carrier)
- `<catalog>.<schema>.<prefix>_otel_spans` — the `predict_fn` span, whose attributes hold
  `task_id`, `trial`, `passed`, `errored`, `error`

```sql
WITH mine AS (
  SELECT trace_id,
    regexp_extract(trace_metadata::string, '"mlflow.sourceRun":"([a-f0-9]+)"', 1) AS run_id,
    regexp_extract(trace_metadata::string, '(?<!cache_read_)input_tokens[^0-9]*([0-9]+)', 1) AS in_tok,
    regexp_extract(trace_metadata::string, 'output_tokens[^0-9]*([0-9]+)', 1) AS out_tok
  FROM <prefix>_trace_metadata
  WHERE regexp_extract(trace_metadata::string, '"mlflow.sourceRun":"([a-f0-9]+)"', 1)
        IN (<run ids from the tag query>)
)
SELECT m.run_id, m.in_tok, m.out_tok,
  regexp_extract(s.attributes::string, '"task_id":"([^"]+)"', 1) AS task,
  regexp_extract(s.attributes::string, '"trial":([0-9]+)',      1) AS trial,
  regexp_extract(s.attributes::string, '"passed":(true|false)',  1) AS passed,
  regexp_extract(s.attributes::string, '"errored":(true|false)', 1) AS errored,
  regexp_extract(s.attributes::string, '"error":"([A-Za-z]+)',   1) AS err_class
FROM mine m
JOIN <prefix>_otel_spans s
  ON s.trace_id = m.trace_id AND s.name = 'predict_fn'
```

Get the run-id set (and each run's `sweep` / `arm` / `model` tags) from one
`mlflow.search_runs(filter_string="tags.series = '<series>'")` call, then execute the SQL on the
pre-started serverless warehouse. Note the negative lookbehind on `input_tokens` — without it you
sum `cache_read_input_tokens` into input.

**Autologged trace metadata carries no pool/workspace attribution.** If you need to know which
workspace served a trial, get it from run tags or log it per trial; it is not recoverable later.

## The math

1. Aggregate rows into cells keyed `(model, sweep, arm, task)`: n, passes, errors, token sums.
2. For each `(model, task)`, compare each arm cell to the control cell:
   `Δpass = pass(arm) − pass(control)`, `in-ratio = mean_in(arm) / mean_in(control)`, same for out.
3. Summarize across tasks with **median and geometric mean** of the ratios — the geo-mean is the
   honest average of ratios; the median shows whether one task is carrying the result.
4. **Guard zero-token cells out of the geo-mean** and log each skip. A zero-token arm cell means
   the arm never ran (broken wrapper, phantom trials), and `log(0)` would poison everything.
5. Emit an error histogram per `(model, error class)` alongside the ratios. It is where the
   interpretation lives.

Paired-per-task is not optional: task difficulty dominates token counts, so unpaired cell means
compare tasks, not arms.

## Reading the output

- **Zero-token cells → broken arm.** 60 phantom trials, 0 tokens, in one wave (#1294). Check for
  this before believing any efficiency number.
- **Iteration-cap / recursion errors are model signal**, not infra: they separated models cleanly
  on an identical slice (1 vs 6 vs 10 vs 13). Keep them as failures.
- **429 / quota errors are infra noise.** Rerun that model at concurrency 1 under a new baseline
  id; never let quota stand as a model failure.
- **Errored trials never count as pass**, and their tokens still count. Both halves matter — the
  first keeps quality honest, the second keeps efficiency honest.
- **Report per model.** The same arm was a clean win on one model and a regression on another.
- **Watch output tokens as a first-class outcome.** Compression that cuts input often grows
  output; published work shows aggressive ratios *raising* total cost for exactly this reason.

## Cost of building this

~1 hour to write once, then every comparison is a few seconds. The wave built a run-navigating
comparison tool first, abandoned it mid-campaign, and wrote this instead. Write this first.

## Working implementation

`libs/rpw_evals/scripts/harvest_sql.py` — the wave's proven harvester (per-trial pass/error
from predict_fn spans, trace-level token sums including errored burn, zero-ratio geo-mean
guard). Point its `EXP`/`CAT`/`META`/`SPANS` constants at your experiment and tables.
