---
name: project-readme
description: House standard for a project README, anchored on one hard rule — the README leads with a committed, regenerable architecture diagram image. Use when writing, reviewing, or editing a README, adding a diagram to one, or checking a repo against the standard. Trigger on "write a README", "review this README", "the README is out of date", "add an architecture diagram to the README". Covers section order, the diagram contract, consumer- vs contributor-facing splits, and a check-mode checklist.
---

# Project README Standard

A README has one job: a reader who has never seen the repo learns what it is, how it
is shaped, and how to run it, in under two minutes. Paragraphs that describe structure
fail that job. A picture does not.

## The anchor rule (hard requirement)

**Every project README leads with an architecture or asset-flow diagram, as a
committed image.**

Not a link to a rendering service. Not an ASCII box drawing. Not a Mermaid fence that
renders on one host and breaks on the next. A PNG file committed in the repo, shown by
relative path, directly under the one-sentence statement of what the repo is.

The rule has four parts. All four are required:

1. **The PNG is committed** in-repo and referenced by a relative path.
2. **The `.html` source is committed next to the PNG**, with the same basename. Diagrams are
   self-contained HTML — CSS grid, inline SVG — screenshotted by headless Chrome (#966).
3. **The source's leading comment carries the exact render command**, output path included,
   so an agent regenerating the image never has to guess the invocation.
4. **A caption line under the image names the source** and says to regenerate it with
   the `diagram` skill.

Shape:

```markdown
# <project-name>

<One sentence: what this repo is.>

## <Architecture | Layout | Asset flow>

![<alt text>](docs/architecture/<name>.png)

Source: `docs/architecture/<name>.html` (regenerate with the `diagram` skill; render
command in the file header).
```

The first lines of the `.html` source, before `<!DOCTYPE html>`:

```html
<!-- <What this diagram shows>. Render (render.sh ships with the `diagram` skill):
       render.sh docs/architecture/<name>.html docs/architecture/<name>.png -->
```

Then start from the `diagram` skill's `template.html` and replace its `<body>`. There is no
theme header to paste — the house theme is that file's `<style>` block, as CSS custom
properties. Leave it alone.

### Regeneration workflow

A diagram is a claim about current structure. When the structure changes, the diagram
changes **in the same PR**:

1. Edit the `.html` source.
2. Run the `render.sh` command from its header — it measures the page, then screenshots
   that exact size at 2×.
3. Read the regenerated PNG back as an image. This is the `diagram` skill's visual QA
   gate. A page that loads is not a clean diagram.
4. Commit the `.html` and the `.png` together.

**A committed PNG with no committed source is a defect.** Nobody can regenerate it, so
it rots into a picture of a structure the repo no longer has. If you find one, recover
the source or redraw it.

### Legacy `.d2` sources

A pre-#966 diagram has a `.d2` source and a `d2` + `rsvg-convert` header. **Legacy, not
broken** — it still renders, its committed PNG is still valid, and it satisfies the anchor
rule. Two rules: **never author a new `.d2`**, and **port on touch** — rewrite it as HTML
the next time it needs regenerating. Never sweep the repo porting diagrams nobody asked
you to change. Detail: [`reference.md`](reference.md).

### What the diagram shows

Structure: 7–10 nouns and the relationships between them. For a monorepo, the assets and
where each one fans out to. For an app, the runtime pieces and what talks to what. For a
library, the modules and their consumers. Editorial choices, the highlight palette, and
the letterbox rule all live in the `diagram` skill. Do not re-derive them here.

## The house shape

A repo-root README, in this order:

1. `# <name>`, then **one sentence** saying what the repo is. No preamble, no badges.
2. **The diagram**, with its caption line.
3. **Layout** — paths mapped to purposes, one line each. A bullet list for a repo, a
   fenced tree for a single package, a table for modules. Every top-level path a
   newcomer would open appears exactly once.
4. **Getting started** — copy-pasteable commands in a fenced block, in the order you
   run them. Name the prerequisites and where they come from.
5. **Verify** — the one gate command, and what it needs. Say when it runs offline, so
   the reader knows it costs nothing.
6. **What this project needs** — routes, configuration table, deploy targets, operations.
7. **Why `<non-obvious decision>`** — see the rules below.
8. **License** — one line, linked. Repo root only; a nested README omits it.

A nested README (one package, one app, one lib) uses the same order and stays short:
about 40–120 lines. Depth belongs in `docs/` and in the package's agent-instructions
file. The README links to them.

## Rules

**Lead with the noun, not the pitch.** "A service that serves static files out of an
object-store volume over HTTP." Not "a powerful, flexible hosting solution."

**Say what it does not do.** A `Not included` or `v1 excludes` or `Not a <thing>`
section prevents the most expensive misread. It is as load-bearing as the feature list.

**Explain a decision that looks wrong.** Where a reader would file a bug against a
deliberate choice, add a short `Why …` section that states the constraint. A vendored
copy that looks like duplication, or a cache whose only invalidation is a TTL, each
need one paragraph.

**Link, do not restate.** Decisions live in ADRs. Conventions live in the
agent-instructions file. Deep design lives in `docs/`. The README cites them by path in
one clause and moves on. A README that re-explains an ADR creates a second source of
truth, and one of the two is already wrong.

**Cite the issue behind a surprise.** For a non-obvious default, a port choice, or a
workaround, name the issue number inline. It turns "why is this like this" into one click.

**Tables for enumerable surfaces.** Routes, configuration variables, modules, servers,
make targets: a table with a "what it does" column. A prose list of five or more items
is unreadable.

**Commands must be copy-pasteable.** Fenced, one command per line, with real values or
clearly marked placeholders. A command the reader must edit before running is a step
you did not document.

**No badge rows, no table of contents, no emoji headings.** They add scrolling before
the content and they go stale.

**Prose follows `simple-english` pragmatic mode.** Short sentences, active voice, one
word per concept, no hedges. That skill holds the rules. Do not duplicate them here.

## Two audiences, two files

A consumer README and a contributor README are different documents:

- **Consumer-facing** (what a public mirror or package page shows): install,
  prerequisites, what is in it, how to update, license, and the honest scope limit —
  what the project is opinionated about, and where to send feedback.
- **Contributor-facing** (the working repo root): layout, gates, branching, release and
  publish mechanics, versioning.

One README that serves both serves neither. If a repo can only have one file, the
consumer sections come first.

## Experiment and evaluation READMEs

An experiment README's deliverable is a findings matrix, not a layout section. Use the
`shareables-experiment` skill for that shape. The anchor rule still applies when the
experiment has infrastructure worth drawing.

## Check mode

When you write, edit, or review a README, run this list. Report each failure with the
file path and the fix.

- [ ] **Diagram present**, above the fold, directly after the one-sentence intro.
- [ ] **PNG committed** — `git ls-files` finds it, the relative path resolves, the file exists.
- [ ] **Source committed** — an `.html` (or a legacy `.d2`) with the same basename sits next
      to the PNG.
- [ ] **Source regenerable** — its header carries its render command, and running it
      reproduces the PNG.
- [ ] **Diagram current** — its nouns match the repo's structure today.
- [ ] **Caption** names the source path and the `diagram` skill.
- [ ] **One-sentence intro** says what the thing is, in nouns.
- [ ] **Layout section** maps paths to purposes, and every path it names exists.
- [ ] **Commands copy-pasteable and current** — every target it names exists.
- [ ] **Verify section** names the gate command.
- [ ] **No restated ADRs** — decisions are linked, not re-explained.
- [ ] **No badges, table of contents, or emoji headings.**
- [ ] **Prose passes the `simple-english` self-check.**

An unchecked box is a finding. Fix it in the same change that brought you to the file.
A README you touched and left below standard is worse than one you never opened,
because it now looks reviewed.

## Composes with

- **`diagram`** — authoring, `template.html`, `render.sh`, visual QA. Every rendering
  question delegates to that skill.
- **`simple-english`** — the prose rules.
- **`shareables-experiment`** — findings-matrix READMEs.
- **`multi-project-monorepo`** — the project index and the consumer/contributor split
  for a repo that publishes a filtered mirror. Its own directory is a working example
  of the anchor rule: `fanout-topology.png` committed beside its source (a legacy `.d2`).

Annotated templates, a worked before/after, and the failure modes each rule prevents:
[`reference.md`](reference.md).
