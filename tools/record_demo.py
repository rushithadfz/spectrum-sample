"""
Record a walkthrough video of the incentives experience.

Dev tool, not part of the app. Requires the dev extras and a running server:

    pip install -r requirements-dev.txt
    python -m playwright install chromium
    python manage.py runserver          # in another terminal
    python tools/record_demo.py

Writes demo/incentives-walkthrough.webm.
"""

import pathlib
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = pathlib.Path("demo")
SIZE = {"width": 1440, "height": 900}


def beat(page, ms=900):
    """A pause long enough to read the frame."""
    page.wait_for_timeout(ms)


def glide(page, to=1200, steps=26):
    """Smooth scroll, so reveal-on-scroll animations actually play on camera."""
    for i in range(steps):
        page.mouse.wheel(0, to / steps)
        page.wait_for_timeout(28)


def record():
    OUT.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport=SIZE,
            record_video_dir=str(OUT),
            record_video_size=SIZE,
            device_scale_factor=1,
        )
        page = context.new_page()

        # ---------- 1. Sign in as the field agent ----------
        page.goto(f"{BASE}/login/", wait_until="networkidle")
        beat(page, 2200)                       # XP ring + counters animate in
        page.click("[data-persona='field-agent']")
        beat(page, 700)
        page.click("#enterBtn")
        page.wait_for_url(f"{BASE}/**", wait_until="networkidle")
        beat(page, 1500)

        # Dismiss the streak overlay if it is showing.
        if page.locator("#arrivalGo").count():
            page.click("#arrivalGo")
            beat(page, 700)

        # ---------- 2. Home: quests and active incentives ----------
        glide(page, 520)
        beat(page, 1100)                       # Daily Quests

        claim = page.locator(".quest-claim").first
        if claim.count():
            claim.scroll_into_view_if_needed()
            beat(page, 600)
            claim.click()                      # XP toast + confetti
            page.wait_for_load_state("networkidle")
            beat(page, 2600)

        glide(page, 900)
        beat(page, 1400)                       # trend, badges, Spectrum House
        glide(page, 700)
        beat(page, 1600)                       # active incentive cards

        # ---------- 3. The incentives feed ----------
        page.goto(f"{BASE}/incentives/feed/", wait_until="networkidle")
        beat(page, 1500)
        glide(page, 800)
        beat(page, 1300)                       # Ending Soon
        glide(page, 900)
        beat(page, 1600)                       # Previous incentives table

        # ---------- 4. Programme detail: points and tiers ----------
        page.goto(f"{BASE}/incentives/detail/", wait_until="networkidle")
        beat(page, 1800)                       # rank + movement arrow
        glide(page, 620)
        beat(page, 1900)                       # tier ladder
        glide(page, 700)
        beat(page, 1700)                       # points structure + MTD

        # ---------- 5. Earnings calculator ----------
        page.goto(f"{BASE}/incentives/calculator/", wait_until="networkidle")
        beat(page, 1300)
        target = page.locator("button.chip", has_text="$500").first
        if target.count():
            target.click()                     # $500 target -> 44 units, 8.8/day
            page.wait_for_load_state("networkidle")
            beat(page, 2400)
            glide(page, 420)
            beat(page, 1600)

        # ---------- 6. Close on the incentive cards ----------
        page.goto(f"{BASE}/home/", wait_until="networkidle")
        glide(page, 1500)
        beat(page, 1800)

        context.close()                        # flush the video
        browser.close()

    videos = sorted(OUT.glob("*.webm"), key=lambda f: f.stat().st_mtime)
    if not videos:
        print("No video produced.")
        return 1

    final = OUT / "incentives-walkthrough.webm"
    if final.exists():
        final.unlink()
    videos[-1].rename(final)
    for stray in OUT.glob("*.webm"):
        if stray != final:
            stray.unlink()

    print(f"Wrote {final}  ({final.stat().st_size / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(record())
