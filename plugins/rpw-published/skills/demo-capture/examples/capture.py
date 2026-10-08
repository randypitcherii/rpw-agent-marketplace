"""Pacing skeleton for a scripted demo recording (GIF source + stills).

Two variants of the same flow: standalone against any reachable URL, and inside a
repo's pytest Playwright harness. Replace the marked steps with your flow; keep the
assertions and beats — they are what make the recording provable and watchable.

Run standalone:  uv run --with playwright python capture.py  (playwright install first)
"""

from __future__ import annotations

# ── Standalone variant ──────────────────────────────────────


def record_flow(base_url: str, out_dir: str = "/tmp") -> None:
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()  # headless is fine; recording still works
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=out_dir,
            record_video_size={"width": 1440, "height": 900},
        )
        page = context.new_page()

        page.goto(base_url)
        # STEP 0: assert the app is loaded before acting — never record a loading screen.
        expect(page.get_by_role("main")).to_be_visible(timeout=30_000)
        page.wait_for_timeout(800)  # settle beat: let the viewer orient

        # STEP 1: the flow. Assert → hover-beat → click, linger on states that matter.
        page.get_by_role("button", name="Open menu").click()
        item = page.get_by_role("menuitem", name="The thing being demoed")
        expect(item).to_be_visible()
        item.hover()
        page.wait_for_timeout(1200)  # the frame reviewers remember
        page.screenshot(path=f"{out_dir}/1-menu.png")

        item.click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        page.wait_for_timeout(1500)
        page.screenshot(path=f"{out_dir}/2-dialog.png")

        dialog.get_by_role("button", name="Confirm").click()
        expect(page.get_by_role("dialog")).to_have_count(0, timeout=30_000)
        page.wait_for_timeout(2500)  # END ON THE AFTER STATE — GIFs loop
        page.screenshot(path=f"{out_dir}/3-after.png")

        context.close()  # closing finalizes the .webm — do this BEFORE moving the file
        browser.close()

        from pathlib import Path

        for video in Path(out_dir).glob("*.webm"):
            video.rename(f"{out_dir}/demo.webm")


# ── pytest-harness variant ──────────────────────────────────
# When the repo has a Playwright e2e harness with a seeded-server fixture, reuse it and
# only bring your own recording context. Name the file so it can't be collected by
# accident (or keep it out of the tree) — a demo capture is throwaway, not a test.
#
# def test_capture_demo(browser, seeded_session, tmp_path):
#     base_url, session_id = seeded_session          # repo's real app + data
#     context = browser.new_context(
#         viewport={"width": 1440, "height": 900},
#         record_video_dir=str(tmp_path),
#         record_video_size={"width": 1440, "height": 900},
#     )
#     page = context.new_page()
#     page.goto(f"{base_url}/c/{session_id}")
#     # ... same assert → hover-beat → click → linger pattern ...
#     context.close()
#     for video in tmp_path.glob("*.webm"):
#         video.rename("/tmp/demo.webm")
#
# Then: ./webm_to_gif.sh /tmp/demo.webm /tmp/demo.gif
