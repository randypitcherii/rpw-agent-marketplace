# TDD — reference

Deeper material for the `tdd` skill. Read this when the lean SKILL.md isn't enough.

## Why watch the test fail first

A test you never saw red proves nothing about your code — it might pass because of a typo in the assertion, an import that no-ops, a fixture that swallows the case, or because the behavior already existed. The RED step is a control: it confirms the test can detect the absence of the behavior. If RED doesn't fail, or fails with the wrong error (ImportError, SyntaxError, fixture crash), fix the *test* before writing any product code.

## Minimum-code GREEN

In GREEN, resist writing more than the failing test demands. Speculative generality ("I'll need this param later") is untested code riding in on a green bar. If you want the abstraction, write the next failing test that forces it. The test suite is the spec; code with no test behind it is liability, not progress.

## "Test pressure" heuristic

If a behavior is hard to write a test for, that's a design signal, not a reason to skip the test. Hard-to-test usually means: too many responsibilities in one unit, hidden global state, or an effect tangled with a decision. Let the difficulty push you toward a seam (inject the dependency, split the decision from the effect) rather than toward an un-tested commit.

## Full-path verification — concrete

The repo has live examples where isolated tests passed but the integrated path was broken:

- A custom `BaseChatModel` wrapper unit-tested fine with a fake member but failed live because `tool_choice=None` was forwarded literally and langchain rejected it (#232). The unit test never exercised the real langchain call path.
- CLI-provider ChatModel wrappers (#235/#236) hit the same class of langchain-unrecognized-class / `max_retries`-forwarding bugs that fake-member tests can't see.

Rule of thumb: when your change sits behind a framework that does its own validation/dispatch (langchain, an MCP proxy, a CLI subprocess, a router), a passing unit test is necessary but not sufficient. Add one test (or one live invocation) that goes through the real machinery.

## The assertion-only carve-out (#199), expanded

The standard loop is RED-first. The exception: you're hardening an *existing, passing* behavior by adding assertions to a test that already passes. There's no behavior gap to make red — the code already does the thing; you're pinning it so a future regression turns red. Run it green, confirm it's actually asserting (mutate the source briefly to see it fail if in doubt), and move on. Do **not** stretch this carve-out to cover new behavior — new behavior always starts red.

## Choosing the gate

- During the loop: run the single test (`pytest file::test`) or the one file. Fastest feedback.
- Before declaring a unit done: run the suite for the package you touched (`make runtime-test` for `libs/rpw_runtime`, `make eval-test` for `libs/rpw_evals`, `make check` for repo invariants).
- Before delivery / PR: run the full project gate (`make verify`).
- Live evals (`make eval`) cost real compute and hit Databricks — run only when the change affects eval behavior and you need live evidence. (Compute itself is free for this user; the cost is wall-clock and network, not dollars.)

## Anti-patterns

- Declaring "fixed" after editing code with no test run.
- A test that asserts the implementation (mock call counts) instead of the behavior.
- Skipping RED because "it's obviously going to fail" — then it passes for the wrong reason and you never notice.
- Trusting a green unit test for a framework-wrapper change (see full-path section).
- Reaching for `python3` / system pip — always `uv run`.
