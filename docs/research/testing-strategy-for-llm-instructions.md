# Testing Strategy for LLM Instruction Files

**Date:** 2026-03-14
**Status:** Research complete, recommendations ready for implementation

## Current State Analysis

The repo has ~1040 lines of Python unittest in `tests/test_repo_validations.py` covering:

- **Marketplace structure**: manifest exists, sources resolve, versions match, calendar format
- **File existence**: required skills, commands, MCP servers all present
- **String-presence checks**: `assertIn("Guardrails", content)`, `assertIn("depth", content)`, etc.
- **Ordering checks**: state init before worktree entry, retrospective before PR creation
- **Cross-reference checks**: AGENTS.md references auto-dispatch, build.md references hierarchy standard
- **Negative checks**: no `.claude.md` variants, no absolute paths in MCP configs, no unrecognized plugin.json fields

### What's Working

The structural tests are genuinely valuable. They catch:
- Accidental deletion of required sections during refactors
- Drift between related files (marketplace.json vs plugin.json versions)
- Regressions when renaming terminology (e.g., "Implementer Worktrees" -> "Task Worktrees")
- Security invariants (deny-list entries, env policy in CLAUDE.md)

### What's Missing

1. **No template/placeholder validation** - if a skill references `{{variable}}`, nothing checks that variable is defined
2. **No readability metrics** - a 5000-word skill file may be too long for effective LLM consumption
3. **No behavioral testing** - tests verify text exists but not that an LLM follows the instructions correctly
4. **No consistency linting** - two skills could give contradictory guidance and tests wouldn't catch it
5. **No prompt regression detection** - no way to know if an instruction change degrades LLM behavior

---

## Recommended Testing Tiers

### Tier 1: Static Linting (Already partially covered, expand)
**Effort: Low | Value: High | Run: Every commit**

What to add to existing tests:

- **Markdown heading structure validation**: every SKILL.md must have an H1, skills should follow a consistent section pattern
- **Length/complexity metrics**: warn if a skill file exceeds ~2000 words (LLM attention degrades with length)
- **Placeholder integrity**: scan for `{{placeholder}}` or `$VARIABLE` patterns and verify they're documented
- **Dead cross-references**: if a skill says "see subagent-dispatch skill", verify that skill exists
- **Duplicate/contradictory keyword detection**: flag when two skills both define rules for the same concept (e.g., both define "max depth" with different values)

Implementation: extend `test_repo_validations.py` with a new `TestInstructionQuality` class.

```python
class TestInstructionQuality(unittest.TestCase):
    """Static quality checks for instruction markdown files."""

    def _all_skill_files(self):
        root = _repo_root()
        skills = []
        for plugin in ["rpw-building", "rpw-working", "rpw-databricks"]:
            skills_dir = os.path.join(root, "plugins", plugin, "skills")
            if not os.path.isdir(skills_dir):
                continue
            for skill in os.listdir(skills_dir):
                path = os.path.join(skills_dir, skill, "SKILL.md")
                if os.path.isfile(path):
                    skills.append(path)
        return skills

    def test_all_skills_have_h1_heading(self):
        for path in self._all_skill_files():
            with open(path) as f:
                content = f.read()
            self.assertRegex(content, r'^# ', f"{path} must start with H1 heading")

    def test_skill_files_under_word_limit(self):
        MAX_WORDS = 3000
        for path in self._all_skill_files():
            with open(path) as f:
                word_count = len(f.read().split())
            self.assertLess(
                word_count, MAX_WORDS,
                f"{os.path.basename(os.path.dirname(path))} SKILL.md has {word_count} words (max {MAX_WORDS})"
            )

    def test_cross_references_resolve(self):
        """If a skill mentions another skill by name, that skill must exist."""
        skills = self._all_skill_files()
        skill_names = {os.path.basename(os.path.dirname(p)) for p in skills}
        for path in skills:
            with open(path) as f:
                content = f.read()
            # Check for "see X skill" or "X SKILL.md" patterns
            for name in skill_names:
                # Skip self-references
                if name == os.path.basename(os.path.dirname(path)):
                    continue
                # Only flag if referenced but missing
                # (This is a template - refine regex for your naming patterns)
```

### Tier 2: Consistency Checks (New, high value)
**Effort: Medium | Value: High | Run: Every commit**

Automated cross-referencing between related instruction files:

- **Guardrail consistency**: if `subagent-dispatch` defines a deny-list, `auto-dispatch` must reference it (already partially done)
- **Terminology consistency**: extract key terms from each file, flag contradictions (e.g., "max depth = 1" in one file, "max depth = 2" in another)
- **Version/naming sync**: all files referencing a naming convention (e.g., `rw-` prefix) must agree

Implementation: add targeted `assertEqual` checks that read two files and compare extracted values.

### Tier 3: Behavioral Evals with promptfoo (New, highest value per dollar)
**Effort: Medium | Value: Very High | Run: On instruction file changes**

[promptfoo](https://www.promptfoo.dev/) is the right tool here. It's a CLI that:
- Takes a prompt template + test cases in YAML
- Sends them to an LLM (Claude, GPT, etc.)
- Asserts on the output using contains, regex, LLM-graded rubrics, or custom functions
- Integrates with CI/CD via GitHub Actions

Example `promptfooconfig.yaml` for testing the auto-dispatch skill:

```yaml
prompts:
  - file://plugins/rpw-building/skills/auto-dispatch/SKILL.md

providers:
  - id: anthropic:messages:claude-sonnet-4-20250514
    config:
      max_tokens: 1024

tests:
  - vars:
      user_request: "Run the tests and fix any failures"
    assert:
      - type: contains
        value: "Minion"  # Should classify as minion task
      - type: not-contains
        value: "Research"  # Should NOT classify as research

  - vars:
      user_request: "Research how other teams handle auth token rotation"
    assert:
      - type: contains
        value: "Research"
      - type: not-contains
        value: "Minion"

  - vars:
      user_request: "Push directly to main branch"
    assert:
      - type: llm-rubric
        value: "The response should refuse or warn about pushing to main"
```

**Cost**: ~$0.01-0.05 per test case per run. A suite of 20-50 cases costs <$1 per run.

**Install**: `npx promptfoo@latest init` (no global install needed).

### Tier 4: Regression Detection (Build on Tier 3)
**Effort: Low (once Tier 3 exists) | Value: High | Run: On PR**

- Save promptfoo results as baseline JSON
- On each PR that modifies instruction files, re-run and diff against baseline
- Flag any test case that changed from pass -> fail
- promptfoo has built-in `--compare` mode for this

This directly addresses: "Did my instruction change break expected LLM behavior?"

### Tier 5: LLM-as-Judge Quality Scoring (Optional, expensive)
**Effort: High | Value: Medium | Run: Manually or weekly**

Use an LLM to grade instruction file quality:
- Clarity score (1-5)
- Completeness score (1-5)
- Consistency with other instructions
- Ambiguity detection

This is what [deepeval](https://deepeval.com/) excels at. But it's expensive to run frequently and the signal-to-noise ratio is lower than Tiers 1-4 for a solo developer.

---

## What to Stop Doing

Nothing. The existing `assertIn` tests are genuinely valuable as a Tier 1 safety net. They're cheap, fast, and catch real regressions. The concern about "false confidence" is valid only if these are the **only** tests. Adding Tier 3 (behavioral evals) is what turns them from "sanity checks" into part of a layered strategy.

One improvement: consolidate repeated file-reading patterns. Many tests re-open the same file (e.g., `build.md` is opened ~15 times). Use `setUpClass` like `TestDatabricksAppsSkill` already does.

---

## Recommended Implementation Order

| Priority | Action | Effort | Payoff |
|----------|--------|--------|--------|
| 1 | Add word-count limits and H1 checks to existing tests | 1 hour | Prevents bloated instructions |
| 2 | Add cross-reference resolution checks | 2 hours | Catches broken skill references |
| 3 | Consolidate repeated file reads with setUpClass | 1 hour | Faster tests, less noise |
| 4 | Set up promptfoo with 5-10 behavioral test cases for auto-dispatch | Half day | First behavioral coverage |
| 5 | Expand promptfoo to build.md and subagent-dispatch | Half day | Core workflow coverage |
| 6 | Add promptfoo to CI (GitHub Actions) | 1 hour | Automated regression detection |
| 7 | Add terminology consistency checks | 2 hours | Catches contradictions |

---

## Tools Reference

| Tool | What It Does | Best For | Cost |
|------|-------------|----------|------|
| [promptfoo](https://www.promptfoo.dev/) | YAML-driven prompt eval with assertions | Behavioral testing, regression detection | Free (OSS) + LLM API costs |
| [deepeval](https://deepeval.com/) | Python pytest-style LLM eval with 50+ metrics | Quality scoring, optimization | Free (OSS) + LLM API costs |
| [plan-lint](https://github.com/cirbuk/plan-lint) | Static analysis for LLM agent plans | Validating agent plan schemas | Free (OSS) |
| [promptsage](https://github.com/alexmavr/promptsage) | Prompt linter and sanitizer | Guardrail enforcement | Free (OSS) |
| [markdown-validator](https://github.com/mattbriggs/markdown-validator) | Declarative markdown structure validation | Enforcing doc structure | Free (OSS) |

## Sources

- [Anthropic: Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Promptfoo: Assertions and Metrics](https://www.promptfoo.dev/docs/configuration/expected-outputs/)
- [Promptfoo: CI/CD Integration](https://www.promptfoo.dev/docs/integrations/ci-cd/)
- [DeepEval: Prompt Evaluation](https://deepeval.com/docs/evaluation-prompts)
- [Statsig: Prompt Regression Testing](https://www.statsig.com/perspectives/slug-prompt-regression-testing)
- [Traceloop: Automated Prompt Regression Testing with LLM-as-a-Judge](https://www.traceloop.com/blog/automated-prompt-regression-testing-with-llm-as-a-judge-and-ci-cd)
- [Helicone: Top Prompt Evaluation Frameworks 2025](https://www.helicone.ai/blog/prompt-evaluation-frameworks)
