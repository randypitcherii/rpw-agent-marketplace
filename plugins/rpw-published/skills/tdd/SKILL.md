---
name: tdd
description: Use when writing tests first, doing test-driven development, or when the user says "write tests first", "this test should fail", "red-green", "TDD", or "add a failing test before the fix". House RED-GREEN-REFACTOR loop with this repo's test invocations and gates. Pairs with systematic-debugging for the fix side.
---

# Test-Driven Development (house version)

Distilled house TDD. Harness-neutral — no Claude-Code-only assumptions. For deeper rationale and edge cases, read `reference.md` in this skill directory.

**Core loop: RED → GREEN → REFACTOR.** Write a failing test first, make it pass with the minimum code, then clean up. Never declare a fix or feature working without a test that proves it.

## The loop

1. **RED** — Write one test that asserts the behavior you want. Run it. **Watch it fail for the right reason** (asserts the gap, not a typo/import error). A test you never saw fail proves nothing.
2. **GREEN** — Write the minimum code to pass. No extra features, no speculative abstraction. Run the test; watch it pass.
3. **REFACTOR** — With the test green, clean up names, dedup, structure. Re-run the test after each change. Green stays green.

Repeat per behavior. Small loops beat big ones.

## House specifics

**Run tests with `uv run`, never bare `python`/`python3`:**

```bash
uv run python -m pytest path/to/test_x.py::test_name   # single test, fast feedback
uv run python -m pytest path/to/test_x.py              # one file
uv run python -m unittest tests.test_repo_validations -v
```

**Gates (run before declaring done):**

| Gate | Command | Scope |
|------|---------|-------|
| Repo invariants | `make check` | structure/validation, no network |
| Full gate | `make verify` | the project gate (alias of check) |
| Runtime units | `make runtime-test` | `libs/rpw_runtime`, fast, no network |
| Eval units | `make eval-test` | `libs/rpw_evals`, fast, no network |

Run the **narrowest** gate that covers your change during the loop; run the full gate before delivery.

## Full-path verification

Test what the user actually hits — the **complete request flow**, not just the new function in isolation. If the real path goes through a proxy, router, CLI wrapper, or multiple hops, the test must exercise the full path. An isolated unit test passing while the integrated path is broken is the most common false "done".

## Two carve-outs that change the loop

- **Assertion-only additions (#199):** Adding assertions to an *already-passing* test to lock in existing behavior doesn't need its own prior RED — the code already works; you're documenting a guarantee. Still run it green. This is the one case where "no failing test first" is fine.
- **Custom LLM/ChatModel wrappers (#232/#235/#236):** Fake-member unit tests miss a whole bug class in `BaseChatModel`/`create_*` wrappers (literal `tool_choice=None`, `max_retries` forwarding, langchain-unrecognized-class). A green unit test here is **not** sufficient evidence. Do a cheap **live routing check** first. Databricks Model Serving / eval compute is free — don't gate on cost.

→ Details, anti-patterns, and the "test pressure" heuristic: `reference.md`.
