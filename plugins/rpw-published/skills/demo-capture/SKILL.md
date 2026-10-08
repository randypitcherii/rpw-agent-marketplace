---
name: demo-capture
description: Record a real UI flow as an animated GIF plus key-moment screenshots for PR demos — drive the app with Playwright video recording, pace it for viewers, convert webm to GIF with a uv-fetched ffmpeg (no system install), host on a throwaway branch so artifacts embed inline via gh. Trigger on "record a demo", "make a GIF of this flow", "demo for the PR", "capture this UI behavior", or any UI-change PR needing visual evidence. NOT for concept diagrams (diagram skill) or data charts (dataviz).
---

# Demo Capture

Produce the two demo artifacts reviewers actually read — a **short animated GIF** of the
flow and a **stills table** of key moments — by scripting the real app instead of
screen-recording your hands. Scripted capture is repeatable, provable (every frame sits
behind a Playwright assertion), and redoable after review feedback in seconds.

The pipeline: **drive → record → pace → convert → host → embed**.

## When to invoke

- A PR touches UI and its template asks for a demo (most do).
- An issue needs visual evidence of a bug ("the dialog never closes").
- Before/after comparisons for a behavior change.

GIF first, stills second. The GIF carries the flow; the stills let a skimmer jump straight
to the moment they care about and render in contexts where GIFs don't autoplay.

## Why GIF, not video

GitHub only renders videos as inline players when uploaded through the web UI as
attachments — there is no API for that, so an agent cannot do it. A video file linked from
a branch renders as a bare link. **A GIF is an image**: it embeds inline from any public
URL and plays automatically. That is the whole reason for the conversion step.

## 1. Drive — script the real app with Playwright

Use the repo's own e2e_ui / Playwright harness when it has one (seeded server fixtures
give you a real app with real data). Standalone `sync_playwright` against any reachable
URL works otherwise. Record video on the browser **context**:

```python
context = browser.new_context(
    viewport={"width": 1440, "height": 900},
    record_video_dir=str(out_dir),
    record_video_size={"width": 1440, "height": 900},
)
page = context.new_page()
# ... drive the flow ...
context.close()  # closing finalizes the .webm file
```

The video file only materializes on `context.close()` — in pytest, close the context
before the assertion that moves/renames the file, not in a fixture teardown.

Take stills in the same run: `page.screenshot(path=...)` at each key moment, after the
element is visible and stable.

## 2. Pace — the recording is for a human, the assertions are for you

A scripted flow at full speed is unwatchable — menus flash for 100 ms. Insert deliberate
beats, and make every beat provable:

- **Assert before act**: `expect(item).to_be_visible()` before every click. If the
  assertion passed, the frame provably contains the moment.
- **Hover before click**: `item.hover(); page.wait_for_timeout(1200)` on the menu item
  the demo is about — that is the frame reviewers screenshot in their heads.
- **Linger on states that matter**: 1.5–2.5 s on the opened menu, the dialog, the
  finished "after" state. Total runtime 6–15 s; longer is a video, not a demo.
- **End on the after state** so the loop restarts cleanly (GIFs loop forever).
- One flow per GIF. Two flows = two GIFs.

A working pacing skeleton lives in [examples/capture.py](examples/capture.py).

## 3. Convert — webm → GIF with zero system dependencies

Do not ask the user to install ffmpeg. `imageio-ffmpeg` ships a static ffmpeg binary as a
wheel; fetch it through uv and hand its path to the shell. [webm_to_gif.sh](webm_to_gif.sh)
wraps the whole thing:

```bash
./webm_to_gif.sh /tmp/demo.webm /tmp/demo.gif
```

The guts, in case they need adapting: a two-pass palette filter is what keeps a 1440×900
UI recording crisp and small — `fps=12` (UI flows read fine at 12 fps), scaled to 1080 px
wide, 128-color palette, bayer dither, `-loop 0`. A 7 s omnigent recording came out at
986 KB. If the result exceeds ~5 MB, drop to `fps=10,scale=900` before trimming content.

## 4. Host — throwaway branch, never the product branch

Artifacts must be reachable at a public URL that will not move, and must not pollute the
PR diff:

1. Commit the GIF + PNGs to a dedicated `demo-assets-<issue>` branch of your **fork**
   (public forks of public repos serve raw files to everyone).
2. Reference `https://raw.githubusercontent.com/<you>/<repo>/demo-assets-<issue>/<file>`.
3. Verify each URL: `curl -sIL <url>` → `200` + `content-type: image/gif|png`.
4. Tell the reviewer (a parenthetical in the Demo section is enough) that the branch is
   image hosting only, and note in your own tracking that it must survive until merge —
   deleting it 404s every image in the PR.

## 5. Embed — the Demo section shape

```markdown
## Demo

<one line naming the flow>

![<flow name>](https://raw.githubusercontent.com/.../demo.gif)

| Menu item | Confirm dialog | After |
| --- | --- | --- |
| ![menu](.../1-menu.png) | ![dialog](.../2-dialog.png) | ![after](.../3-after.png) |
```

`gh pr edit <n> --body-file body.md` updates the body in place — composing locally and
pushing once beats editing in the web UI.

## Failure modes

- **Spawned dev servers inherit your shell env.** When the capture harness boots a server
  as a subprocess, session-scoped variables from *your* agent runtime (runner tokens,
  primary-session ids, log paths) leak into the child and break it in confusing ways —
  e.g. the spawned server polls its own runner status against your session's runner.
  Symptom: the harness times out on health checks that passed earlier in a clean shell.
  Fix: strip the ambient prefix before invoking the test:
  `env $(env | grep -E '^PREFIX_' | cut -d= -f1 | sed 's/^/-u /') <command>`.
- **Blank or 1-frame video**: the context wasn't closed, or the flow ran before the app
  finished loading. Assert the first stable element, then start acting.
- **GIF looks mushy**: you skipped the palette pass and let ffmpeg dither with the default
  256-color global palette, or you scaled below ~900 px. Keep the two-pass filter.
- **Images 404 for reviewers but load for you**: the assets branch is on a private fork,
  or you linked `github.com/.../blob/...` (HTML page) instead of
  `raw.githubusercontent.com/...` (the file).
- **"Demo" older than the code**: recapture after any UI-affecting review fix; a stale GIF
  is worse than none. Scripting makes this a one-command redo.

## Checklist

- [ ] Flow driven against the real app (seeded fixture or live URL), every action behind an assertion
- [ ] Pacing: hover beat on the key control, 1.5 s+ on dialog/after states, ends on the after state
- [ ] GIF ≤ ~5 MB at 1080 px / 12 fps via the two-pass palette
- [ ] Stills at each key moment, named for the moment (`1-menu.png`, not `img1.png`)
- [ ] Artifacts on a `demo-assets-*` fork branch, URLs verified with curl, product branch clean
- [ ] Capture script deleted (throwaway) or committed under tests/ only if it earns keep as a real test
