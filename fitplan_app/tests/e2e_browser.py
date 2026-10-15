"""Browser end-to-end test of the phone app in a mobile viewport (mock LLM).
Needs: pip install playwright && playwright install chromium   (plus the app's requirements)
Run:   python tests/e2e_browser.py        screenshots go to tests/screens/"""
import json
import os
import subprocess
import sys
import tempfile
import time

import requests
from playwright.sync_api import sync_playwright

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
PORT = int(os.getenv("E2E_PORT", "8777"))
BASE = f"http://127.0.0.1:{PORT}"
APP = os.getenv("E2E_APP", "app.main:app")
APP_DIR = os.getenv("E2E_APP_DIR", ROOT)
OUT = os.path.join(ROOT, "tests", "screens")
os.makedirs(OUT, exist_ok=True)

env = dict(os.environ, FITPLAN_MOCK="1", FITPLAN_DB=os.path.join(tempfile.mkdtemp(), "e2e.db"), FITPLAN_AUTO_ADAPT="0", FITPLAN_AUTOPILOT="0")
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "--app-dir", APP_DIR, APP, "--port", str(PORT), "--log-level", "warning"], env=env, cwd=ROOT)
errors, failures = [], []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


try:
    for _ in range(60):
        try:
            requests.get(BASE + "/api/v2/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    with sync_playwright() as pw:
        exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
        try:
            slow = int(os.getenv("E2E_SLOWMO", "0"))           # ms between actions, so a recording is watchable
            browser = pw.chromium.launch(executable_path=exe, slow_mo=slow) if exe else pw.chromium.launch(slow_mo=slow)
        except Exception:
            browser = pw.chromium.launch()
        video = os.getenv("E2E_VIDEO")                 # set to a folder to record the run as a video
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                                  **({"record_video_dir": video, "record_video_size": {"width": 390, "height": 844}} if video else {}))
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and "cdnjs" not in m.text and "net::" not in m.text and errors.append(m.text))
        page.set_default_timeout(15000)
        shot = lambda name: page.screenshot(path=os.path.join(OUT, name), full_page=True)

        page.goto(BASE + "/")
        page.wait_for_selector("text=What do you want to do?")
        check(page.locator("#tabs").is_hidden(), "tab bar hidden during onboarding")
        shot("01_onboarding.png")
        page.click("text=Run a 10K")
        page.click("[data-act=next]")
        page.fill("#ob-age", "30")
        page.select_option("#ob-weeks", "8")
        page.select_option("#ob-days", "4")
        page.click("[data-act=next]")
        page.fill("#ob-inj", "old ankle sprain")
        page.click("[data-act=build]")
        page.wait_for_selector(".strip", timeout=30000)
        check(page.locator("#tabs").is_visible(), "plan built, tab bar visible")
        check(page.locator(".strip .day").count() == 7, "week strip has 7 days")
        shot("02_today.png")
        page.locator(".strip .day:not(.today)").first.click()
        page.wait_for_selector("text=back to today")
        check(page.locator(".sess-card").count() == 1, "tapping another day shows that day's session")
        page.click("text=back to today")
        page.wait_for_selector("[data-act=checkin]")

        page.click("[data-act=checkin]")
        page.wait_for_selector(".sheet #ci-sleep")
        page.wait_for_timeout(450)                      # let the slide-up animation finish
        page.screenshot(path=os.path.join(OUT, "02b_checkin_sheet.png"))
        check(page.locator("#tabs").is_hidden(), "tab bar hides while the check-in sheet is open")
        page.fill("#ci-sleep", "7.2")
        page.locator("#ci-sore").evaluate("e => { e.value = 8; e.dispatchEvent(new Event('input', {bubbles: true})); }")
        page.click("[data-act=savelog]")
        page.wait_for_selector("text=Your coach adjusted your plan", timeout=30000)
        check(page.locator("text=soreness 8/10").count() >= 1, "autopilot card shows the trigger")
        check(page.locator("[data-act=undo]").count() == 1, "autopilot card offers undo")
        shot("03_autopilot.png")
        page.click("text=How the coach decided")
        check(page.locator("text=Eased a session").count() >= 1, "decision steps visible")
        page.click("[data-act=undo]")
        page.wait_for_selector("text=Undone", timeout=10000)
        page.wait_for_timeout(500)
        check(page.locator("[data-act=undo]").count() == 0, "undo removes the card from Today")
        page.click("[data-act=feel][data-v=fresh]")
        page.wait_for_selector("[data-act=feel][data-v=fresh][aria-pressed=true]")
        check(True, "one-tap check-in saves and shows as selected")
        page.screenshot(path=os.path.join(OUT, "03b_today_feel.png"))

        page.click("[data-act=settings]")
        page.wait_for_selector("text=Import a file")
        check(page.locator("#push-key").input_value().startswith("Bearer fps_"), "settings shows the live sync key")
        shot("04_settings.png")
        page.click("[data-act=seed][data-v=overreaching]")
        page.wait_for_selector("text=Demo data added")
        page.click("[data-tab=trends]")
        page.wait_for_selector(".chart svg")
        check(page.locator(".chart svg").count() == 3, "three trend charts render")
        shot("05_trends.png")

        page.click("[data-tab=coach]")
        page.wait_for_selector("text=Autopilot activity")
        check(page.locator("text=undone").count() >= 1, "activity feed shows the undone action")
        page.click("[data-act=adapt]")
        page.wait_for_selector("text=Coach updates", timeout=30000)
        shot("06_coach.png")
        page.click("[data-act=aptoggle]")
        page.wait_for_selector("text=Autopilot off")

        page.click("[data-tab=plan]")
        page.wait_for_selector(".weekbars")
        check(page.locator("text=Checked by your coach team").count() == 1, "plan shows the quality report")
        page.click("[data-act=rate][data-v='1']")
        page.wait_for_selector("text=Thanks for rating this plan")
        page.locator(".wb").nth(3).click()
        page.wait_for_selector("h2:has-text('Week 4')")
        page.locator("details.sess").first.click()
        check(page.locator("details.sess[open] ul.steps li").count() >= 1, "session details expand")
        shot("07_plan.png")

        page.click("[data-tab=today]")
        page.wait_for_selector(".strip")
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        check(not overflow, "no horizontal scroll at phone width")
        check(not errors, "no JavaScript errors" + (f": {errors[:3]}" if errors else ""))

        tok = page.evaluate("localStorage.getItem('fp_token')")
        dark = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, color_scheme="dark")
        dark.add_init_script(f"localStorage.setItem('fp_token', {json.dumps(tok)})")
        dp = dark.new_page()
        dp.on("pageerror", lambda e: errors.append(str(e)))
        dp.goto(BASE + "/")
        dp.wait_for_selector(".strip")
        dp.screenshot(path=os.path.join(OUT, "08_today_dark.png"), full_page=True)
        check(not errors, "no JavaScript errors in dark mode")
        ctx.close()                                  # flushes the video file
        browser.close()
finally:
    srv.terminate()
print("ALL BROWSER TESTS PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
