---
name: agents-md-standards
description: Author a new AGENTS.md, or audit an existing one against the house standard — root-vs-nested split, non-duplication, required sections, length budget, and content that belongs in an ADR, a skill, or a README. Use when adding agent instructions to a package, reviewing an AGENTS.md diff, or checking the tree for drift. Trigger on "write an AGENTS.md", "agent instructions for this package", "audit our AGENTS.md files", "is this AGENTS.md too long", "does this duplicate the root".
---

# AGENTS.md Authoring and Audit

## The rules live in one file — read it first

`docs/process/agents-md.md` is the source of truth: the root-vs-nested split, the
depth rule, the required sections, the routing table for content that does not
belong, the precedence rule, the word budget, and freshness ownership.

**Read it before writing or judging anything.** This skill carries only the
procedure. It deliberately does not restate a threshold or a section list,
because two copies of a rule means one of them is already wrong.

In a repo that has no such document, write one first — the standard is portable,
and an audit with no citable rule produces opinions instead of findings.

## Authoring a new nested file

1. **Check it is owed one.** The standard's depth rule decides. A directory with
   no gate and no invariants does not get a file.
2. **Harvest, do not invent.** Mine the package's real traps before writing a
   word: its `Makefile` gate targets, `git log` messages that say "do not",
   test names and comments that pin a surprising property, and the issues cited
   in its code. An invariant nobody paid for in a bug is not an invariant.
3. **Write the required sections in order**, per the standard. Each invariant is
   one bullet: the rule, what breaks without it, the issue number, and — when
   there is an obvious wrong "cleanup" — an explicit "do not change this back".
4. **Delete every line the root already says.** This is the pass that most new
   files skip.
5. **Link the depth**, do not summarize it: README, `docs/` pages, ADRs by path.
6. **Measure** with `wc -w` and cut to the budget.

## Auditing an existing file

Run the mechanical checks first — they are cheap and produce exact findings:

```bash
git ls-files '*AGENTS.md' | xargs wc -w      # budget + the whole tree at once
git ls-files '*AGENTS.md'                    # depth: no file deeper than one per package

# duplication smell: headings the child shares with the root
comm -12 <(grep -o '^#\+ .*' projects/<pkg>/AGENTS.md | sed 's/^#* //' | sort -f) \
         <(grep -o '^#\+ .*' AGENTS.md | sed 's/^#* //' | sort -f)

# root-owned topics leaking into a child
grep -nE 'build-claim|Refs #|squash|publish|marketplace|version bump|Landing the Plane' \
  projects/<pkg>/AGENTS.md
```

Then the judgment checks, each against a named rule in the standard:

- **Missing required section** — no gate, no invariants, or no handoff line.
- **Duplication with the parent** — the child restates a repo-wide rule. Report
  the root line it duplicates.
- **Contradiction** — the child states a repo-wide rule *differently* from the
  root. This outranks every other finding: an agent following the child is doing
  the wrong thing right now.
- **Wrong home** — decision-with-rationale (an ADR), a repeatable procedure with
  triggers (a skill), reference mechanics (`docs/process/`), install and
  onboarding (the README — see the `project-readme` skill).
- **Stale claim** — a named gate target, path, or file that no longer exists.
  Verify each one; do not assume.
- **Over budget** — cite the count and the cap.
- **Prose bloat** — narrative where a bullet would do. The `simple-english`
  skill holds the rewrite rules.

### Report findings, do not silently fix

One line per finding: `path` → rule violated → the concrete fix.

```
projects/<pkg>/AGENTS.md:41 — duplication (non-duplication rule): restates the
  claim protocol from root AGENTS.md "Worker fencing". Fix: delete; the root
  is already read by every agent.
```

Audits are **advisory**. Fix a file you already own and are already changing;
otherwise file the findings as an issue against the package (`issue-creation`
skill) and let the owning change carry them. Never rewrite another worker's
fenced file mid-wave.

A verdict needs a count, not an adjective: "4 findings, 1 contradiction" beats
"mostly fine".

## Reviewing a diff that touches an AGENTS.md

Two questions, in this order:

1. **Is the change true today?** Every command, path, and gate it names must
   exist at that commit.
2. **Did the change that invalidated the old line come with it?** A renamed gate
   or moved package updates its AGENTS.md in the *same* PR. A PR that moves a
   package and leaves its instructions stale is incomplete.

## Composes with

- **`project-readme`** — the same split, for the human-facing file. Depth,
  onboarding, and the architecture diagram belong there, not here.
- **`simple-english`** — the prose rules an over-long file needs to get under
  its cap.
- **`issue-creation`** — the shape for filing audit findings.
