# Diagram QA

Acceptance has two gates. The browser proves measurable properties and writes evidence;
the author reads the rendered image and judges meaning. Neither replaces the other.

## 1. Machine receipt

Run after every render, with the same `RPW_SCALE` used by `render.sh`:

```bash
./qa.sh /tmp/diagram-<slug>.html /tmp/diagram-<slug>.png
```

The command writes `/tmp/diagram-<slug>.qa.json`. A pass exits 0; findings exit 1;
tooling or input failures exit 2. The receipt records artifact paths, CSS and PNG
dimensions, scale, every check's status, and actionable findings with a subject,
evidence, and supported fixes.

The checker runs after page load, fonts, and a two-second observation window. Chrome
DevTools records attempted HTTP, WebSocket, and WebTransport activity throughout that
window, even if page scripts remove the requesting element or clear Resource Timing.
The geometry checker then runs in a DevTools isolated world and returns the receipt
over Chrome's private DevTools pipe. Content Security Policy and authored page scripts
cannot suppress the checker or provide its receipt.

Chrome checks:

- exactly one title, a one-line subtitle, and canvas width at most 1600 CSS px;
- no non-inline resource references, local-file subresources, or network requests;
- no text outside the canvas or an overflow-clipping ancestor;
- no overlapping text fragments;
- no connector outside its `.conn` gutter, crossing visible text, or crossing another connector;
- connector labels contain at most three words;
- visible text is at least 10 CSS px;
- actual PNG dimensions equal the measured CSS canvas at `RPW_SCALE`;
- the PNG is not blank — flattened onto white, at least 1% of its pixels carry ink.
  Every other check compares boxes that exist, so an empty page violates none of them;
  the receipt records the measured `artifact.nonWhiteShare` on pass as well as fail.

These are deterministic geometry and artifact checks. They do not decide whether a fact
is true, a title answers the reader's question, or a composition communicates well.

`examples/overlap-antipattern.html` must fail; `examples/overlap-fixed.html` must pass.
Use them to test checker changes.

## 2. Human image readback

**Open the PNG as an image.** Do not infer its quality from HTML or a green receipt.

- [ ] **Externally-sourced text is HTML-escaped.** Escape `&`, `<`, `>`, `"`, and `'`.
- [ ] **Every fact is true.** Check each claim against its source.
- [ ] **Title is the answer; subtitle is the reading instruction.** Neither is a topic
      label, and the subtitle fits on one line.
- [ ] **Nothing is clipped**, at any edge.
- [ ] **No dead space** — no wide empty band or mostly-empty card.
- [ ] **No text over text; no connector crossing text or a group border.**
- [ ] **Every label is legible** at the reader's viewing size.
- [ ] **Dimensions match** the receipt and `render.sh` report.

Any unchecked item means fix, render, and run both gates again. Grid tracks resize each
other, so inspect the whole image after every change.

## Collision repair order

| Trigger | Fix |
|---|---|
| Connector leaves its gutter | End at `x≈90`; aim at the group, not a node inside it |
| Back-edge drawn as a long arc | Delete it; state the return path in the subtitle |
| `height` on `.canvas`, `.group`, or `.card` | Remove it; only `<body>` carries `min-height` |
| Edge label longer than three words | Cut to 1–3 words or move the verb into a `.verb` badge |
| One-bullet card beside three-bullet cards | Balance to 2–3 each, or merge |
| Arrowhead stretched or hollow | Use chevrons between cards; SVG markers only in `.conn` gutters |
