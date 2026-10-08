# project-readme reference

Copy-paste templates, a worked before/after, and the failure mode behind each rule in
`SKILL.md`. Read this when you author a README from scratch, or when you need the
argument for a rule someone is pushing back on.

## Template — contributor-facing repo root

````markdown
# <repo-name>

<One sentence. What this repo is, in nouns. No adjectives that carry no fact.>

## <Architecture | Asset flow | Layout>

![<alt text>](docs/architecture/<name>.png)

Source: `docs/architecture/<name>.html` (regenerate with the `diagram` skill; render
command in the file header). <One clause of context the picture cannot carry — a
target that does not exist yet, a migration in flight.>

## Layout

- `<path>/` — <what lives here, and the one thing a newcomer must know about it>
- `<path>/` — <…>. See `docs/decisions/<ADR>.md`.

## Getting started

```bash
<install command>
<run command>
```

<Prerequisite, and where it comes from.>

## Verify

```bash
<gate command>
```

<What it covers. Whether it needs network or credentials.>

## Why <the decision that looks wrong>

<The constraint. Two or three sentences. Not the full ADR.>

## License

Licensed under the [<name>](./LICENSE). Copyright <year> <holder>.
````

## Template — consumer-facing

Ships to a public mirror, a package page, or a plugin marketplace. Different reader,
different document.

````markdown
# <name>

<One or two sentences: what it is, and who it is for.>

<Optional blockquote: the honest boundary. "This is a mirror of a private repo; open
an issue rather than a pull request." Or: "These are the tools I use daily, published
as-is. They lean toward <stack>, because that is what I work in.">

## Install

```bash
<one command, or two>
```

<The first command to run after installing, and what it checks.>

## What's in it

<Tables for the enumerable surfaces. One "what it does" column each.>

## Prerequisites

| To use | You need |
|---|---|
| <component> | <dependency, with a link> |

## Updating

```bash
<update command>
```

## License

[<name>](./LICENSE).
````

Do not put layout, gates, branching, or publish mechanics in this file. A consumer
cannot act on them, and they leak internal process into a public surface.

## Template — the `.html` source

Do not hand-write this file from scratch. Copy `template.html` from the `diagram` skill,
which carries the Brief theme as CSS custom properties, a working stepper row, and an
always-on band — then replace the `<body>` and add the header comment above the doctype:

```html
<!-- <What this diagram shows>. Render (render.sh ships with the `diagram` skill):
       render.sh docs/architecture/<name>.html docs/architecture/<name>.png -->
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>/* ← template.html's <style> block, verbatim */</style></head>
<body>
  <!-- Title + subtitle first, then 5–9 cards or nodes. Yellow (.gate) only where a human acts,
       blue (.brand) for the party you don't control. See the `diagram` skill. -->
</body>
</html>
```

Two properties make the header load-bearing. The command is **absolute about the output
path**, so a regenerating agent writes the PNG back over the committed one instead of
leaving it in a temp directory. And it is **in the file**, so the agent needs no other
document to know what to run. The one thing the header cannot carry is where `render.sh`
lives — that depends on where the plugin is installed, so the header names the script and
the skill that ships it.

Two rules the HTML source must satisfy, both from the `diagram` skill:

- **Zero network requests.** System fonts, inline CSS, inline SVG. No external stylesheet,
  font, or image — the source has to render from an offline clone years from now.
- **No height on `.canvas`, `.group`, or `.card`.** Heights clip silently, and `render.sh`
  measures the laid-out page rather than a window you guessed. Only `<body>` carries a
  `min-height`.

## Legacy `.d2` sources

#966 replaced D2 + librsvg with HTML + headless Chrome (landed in PR #1020). Diagrams
committed before that have a `.d2` source and a two-command `d2 --pad=24` / `rsvg-convert`
header:

```d2
# <What this diagram shows>. Render:
#   d2 --pad=24 docs/architecture/<name>.d2 /tmp/<name>.svg
#   rsvg-convert --zoom 2 --format png --output docs/architecture/<name>.png /tmp/<name>.svg
```

**They are legacy, not broken.** The committed PNG is valid, the source still renders for
anyone with `d2` and `librsvg`, and the pair satisfies the anchor rule. Nothing in this repo
is a finding for being `.d2`.

What changed is the prescription:

| | Then | Now |
|---|---|---|
| Source | `docs/architecture/<name>.d2` | `docs/architecture/<name>.html` |
| Render | `d2 --pad=24` → `rsvg-convert --zoom 2` | `render.sh <in.html> <out.png>` |
| Dependencies | `d2` + `librsvg` | headless Chrome only |
| Theme | a D2 header block copied into every source | CSS custom properties in `template.html` |

That last row is the one that trips authors: **the theme header no longer exists.** An
instruction to "copy the house theme header from the `diagram` skill" has nothing to copy.

**Port on touch, not on sight.** The next time a legacy diagram needs regenerating, rewrite
it as HTML instead of editing the `.d2`; the `diagram` skill's `layout-recipes.md` has the
construct-by-construct conversion table. Do not port diagrams nobody asked you to change —
the PNGs sit at the top of READMEs, so a port changes what a repo's front page looks like,
and that is an aesthetic decision, not cleanup.

## Worked before/after

**Before** — the common shape. Structure described in prose:

```markdown
# platform-tools

This repository contains our internal tooling. It is organized as a monorepo with
several packages. The `core` package contains shared utilities which are consumed by
the `cli` and `service` packages. The `service` package is deployed to our staging and
production environments, while the `cli` package is published to the internal package
registry. There is also a `docs` directory.
```

A reader has to build the graph in their head, and the paragraph goes stale the day a
fourth package lands, with nothing to flag it.

**After:**

```markdown
# platform-tools

Monorepo for the internal platform toolchain: one shared library, one CLI, one service.

## Asset flow

![platform-tools asset flow](docs/architecture/asset-flow.png)

Source: `docs/architecture/asset-flow.html` (regenerate with the `diagram` skill; render
command in the file header).

## Layout

- `core/` — shared utilities. Every other package imports it; nothing imports out.
- `cli/` — command-line client. Published to the internal registry.
- `service/` — HTTP service. Deploys to staging and production.
- `docs/` — decision records and design notes.
```

The graph is now a picture, the prose carries only what the picture cannot (the
import direction rule), and the diagram breaks visibly when a fourth package lands.

## Failure modes, one per rule

| Rule | What goes wrong without it |
|---|---|
| Diagram is a committed image | A rendering-service link dies, and a Mermaid fence renders on one host and breaks on the next. The picture must survive the repo being cloned offline. |
| Source committed beside the PNG | The image cannot be regenerated. It rots into a picture of a structure the repo no longer has, and the next author redraws it from scratch. |
| Render command in the source header | The regenerating agent guesses at scale and output path, and produces an image that does not match the committed one. |
| PNG, not SVG | PNG pastes into chat, issues, and slides. An SVG committed for a README is usually a sign the render step was skipped. |
| One-sentence intro | The reader gets three paragraphs before learning whether the repo is relevant to them. |
| Layout maps paths to purposes | A newcomer opens directories at random. This is the single highest-value section after the diagram. |
| Say what it does not do | Someone builds on an assumed capability. The correction costs a week; the sentence costs ten seconds. |
| Explain the decision that looks wrong | A deliberate constraint gets "fixed" by a well-meaning contributor. |
| Link, do not restate | Two sources of truth. The README copy is always the stale one, because nobody reviews a README when they amend an ADR. |
| Cite the issue behind a surprise | The next reader re-derives an investigation that already happened. |
| Copy-pasteable commands | A command that needs editing before it runs is a command that does not run. |
| No badges or table of contents | Scrolling before content, plus a second maintenance surface that silently drifts. |
| Consumer and contributor split | The public reader wades through branch protection rules; the contributor hunts for the gate command among install instructions. |

## Check mode, run as commands

The checklist in `SKILL.md` is the contract. These are useful mechanical probes:

```bash
# The image the README points at is committed, not just present on disk.
git ls-files docs/architecture/

# A committed PNG with no sibling source (.html, or a legacy .d2) is a defect.
comm -23 \
  <(git ls-files 'docs/architecture/*.png' | sed 's/\.png$//' | sort) \
  <(git ls-files 'docs/architecture/*.html' 'docs/architecture/*.d2' \
      | sed -E 's/\.(html|d2)$//' | sort -u)

# Every relative image reference in the README resolves.
grep -o '!\[[^]]*\]([^)]*)' README.md

# The source header carries its render command.
head -3 docs/architecture/<name>.html

# Regenerate and confirm the committed PNG is current.
render.sh docs/architecture/<name>.html docs/architecture/<name>.png
git status --short docs/architecture/<name>.png   # non-empty means the diagram moved
```

For a legacy `.d2`, the regenerate step is still the two commands in its own header
(`d2 --pad=24` then `rsvg-convert --zoom 2`) — read the header rather than assuming.

The last probe is the important one. A stale diagram passes every static check and is
still wrong. Regenerating and diffing is the only test that catches it. Read the diff as a
signal, not a verdict: a different Chrome (or `d2`) version rewrites bytes without changing
the picture, so **look at the image** before concluding the diagram was stale.

After regenerating, read the PNG back as an image before you commit it. The `diagram`
skill's visual QA gate applies here: a page Chrome loaded without error is not a readable
diagram — it will happily draw a connector straight through a container heading.

## Scope notes

- **Length.** A repo-root README earns more length than a nested one, but neither is a
  manual. When a section grows past a screen, move it to `docs/` and leave a link. A
  README over roughly 150 lines is usually two documents.
- **Nested READMEs.** A package README repeats nothing from the root. It says what this
  package is, its layout, its own verify command, and any decision specific to it.
- **Generated READMEs.** If a README is generated, say so in the first line and name
  the generator. Otherwise a contributor edits the output and loses the change.
