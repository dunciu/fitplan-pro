"""TEST-ONLY: drive the compiled iPhone app (via the React Native stand-in) in Chromium at iPhone size, against a
FitPlan server in mock mode. Checks app logic and every API call; it cannot show native iOS rendering.
  E2E_APP=module:app E2E_APP_DIR=<dir> MOBILE_URL_PATH=/mobile/ python tools/webtest/e2e.py <screens dir>"""
import os
import subprocess
import sys
import tempfile
import time

import requests
from playwright.sync_api import sync_playwright

PORT = 8791
BASE = f"http://127.0.0.1:{PORT}"
OUT = sys.argv[1] if len(sys.argv) > 1 else "screens"
os.makedirs(OUT, exist_ok=True)
env = dict(os.environ, FITPLAN_MOCK="1", FITPLAN_DB=os.path.join(tempfile.mkdtemp(), "m.db"), FITPLAN_AUTO_ADAPT="0", FITPLAN_AUTOPILOT="0",
           GOOGLE_CLIENT_ID="test-client", GOOGLE_CLIENT_SECRET="x", GOOGLE_REDIRECT_URI=f"{BASE}/api/v2/connect/google/callback")
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "--app-dir", os.environ["E2E_APP_DIR"], os.environ["E2E_APP"], "--port", str(PORT),
                        "--log-level", "warning"], env=env)
failures, errors = [], []


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
    # an existing web account with a plan, to pair the phone with
    tok = requests.post(BASE + "/api/v2/session").json()["token"]
    H = {"X-User-Token": tok}
    requests.post(BASE + "/api/v2/onboard?nostream=1", headers=H, json={"goal": "Run a 10K", "age": 30, "weeks": 8, "days_per_week": 4})
    for _ in range(40):
        if not requests.get(BASE + "/api/v2/onboard/status", headers=H).json()["running"]:
            break
        time.sleep(0.25)
    code = requests.post(BASE + "/api/v2/pair/create", headers=H).json()["code"]

    with sync_playwright() as pw:
        exe = "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None
        slow, video = int(os.getenv("E2E_SLOWMO", "0")), os.getenv("E2E_VIDEO")   # pacing + optional recording
        browser = pw.chromium.launch(executable_path=exe, slow_mo=slow) if exe else pw.chromium.launch(slow_mo=slow)
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                                  **({"record_video_dir": video, "record_video_size": {"width": 390, "height": 844}} if video else {}))
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        missing = []
        page.on("response", lambda r: r.status == 404 and missing.append(r.url))
        page.on("console", lambda m: m.type == "error" and "404" not in m.text and errors.append(m.text))
        page.set_default_timeout(15000)
        shot = lambda n: page.screenshot(path=os.path.join(OUT, n))
        tid = lambda t: page.locator(f"[data-testid='{t}']")

        page.goto(BASE + os.getenv("MOBILE_URL_PATH", "/mobile/"))
        page.wait_for_selector("text=Your server")
        tid("base").fill(BASE)
        tid("test").click()
        page.wait_for_selector("text=Connected")
        check(True, "setup: server connection test works")
        tid("code").fill(code)
        shot("m01_setup.png")
        tid("link").click()
        page.wait_for_selector("[data-testid='hero']", timeout=20000)
        check(page.locator("[data-testid^='day-']").count() == 7, "paired with the web account; Today shows the week strip")
        shot("m02_today.png")

        page.locator("[data-testid^='day-']").nth(5).click()
        page.wait_for_selector("text=back to today")
        check(True, "tapping a day shows that day's session")
        page.click("text=back to today")

        tid("checkin").click()
        page.wait_for_selector("text=Leave blank anything")
        tid("ci-sleep_h").fill("7.1")
        page.locator("[data-testid='modal'] [aria-label='8']").first.click()
        shot("m03_checkin.png")
        tid("savelog").click()
        page.wait_for_selector("[data-testid='undo']", timeout=20000)   # the card itself, not the toast with the same words
        check(page.get_by_text("Because: soreness 8/10").count() >= 1, "sore check-in: autopilot card shows the trigger")
        shot("m04_autopilot.png")
        page.click("text=How the coach decided")
        check(page.locator("text=Eased a session").count() >= 1, "decision steps visible")
        tid("undo").click()
        page.wait_for_selector("text=Undone", timeout=10000)
        check(True, "undo works from the phone")
        tid("feel-fresh").click()
        page.wait_for_selector("text=Logged: fresh")
        page.wait_for_selector("[data-testid='feel-fresh'][aria-selected='true']", timeout=10000)
        check(True, "one-tap check-in saves and shows as selected")
        shot("m04b_today_after.png")

        tid("tab-plan").click()
        page.wait_for_selector("text=Checked by your coach team")
        tid("week-4").click()
        page.wait_for_selector("text=Week 4")
        tid("sess-0").click()
        check(page.locator("text=Why:").count() >= 1, "plan: week bars and expandable sessions work")
        shot("m05_plan.png")

        tid("settings").click()
        page.wait_for_selector("text=Fitbit Air and Google Health")
        tid("connect-google").click()
        page.wait_for_function("window.__opened && window.__opened.startsWith('https://accounts.google.com/')")
        opened = page.evaluate("window.__opened")
        check("googlehealth.sleep.readonly" in opened and "access_type=offline" in opened, "Connect Google Health opens Google sign-in with the health scopes")
        shot("m06_settings.png")
        tid("seed-overreaching").click()
        page.wait_for_selector("text=Demo data added")

        tid("tab-trends").click()
        page.wait_for_selector("text=Resting heart rate")
        check(page.get_by_text("the dashed line is your usual").count() == 3, "progress: three charts against your usual")
        shot("m07_progress.png")

        tid("tab-coach").click()
        page.wait_for_selector("text=Autopilot activity")
        tid("autopilot").click()
        page.wait_for_selector("text=Autopilot off")
        check(True, "coach: activity feed and autopilot switch")
        shot("m08_coach.png")

        # live update: data arriving on the server shows up without touching the app (pull-to-refresh / timer / foreground use reload)
        requests.post(BASE + "/api/v2/log", headers=H, json={"sleep_h": 5.2})
        tid("tab-today").click()
        page.wait_for_selector("text=5.2 h sleep")
        check(True, "new data on the server appears in the app on refresh")

        dark = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, is_mobile=True, color_scheme="dark")
        dp = dark.new_page()
        dp.on("pageerror", lambda e: errors.append(str(e)))
        dp.goto(BASE + os.getenv("MOBILE_URL_PATH", "/mobile/"))
        dp.wait_for_selector("text=Your server")
        dp.locator("[data-testid='base']").fill(BASE)
        dp.locator("[data-testid='fresh']").click()
        dp.wait_for_selector("text=What's your goal?")
        dp.click("text=Swim 1500 m")
        dp.locator("[data-testid='next1']").click()
        dp.locator("[data-testid='age']").fill("34")
        dp.locator("[data-testid='next2']").click()
        dp.locator("[data-testid='build']").click()
        dp.wait_for_selector("[data-testid='hero']", timeout=30000)
        check(True, "fresh phone: onboarding builds a plan by polling the server (no streaming)")
        dp.screenshot(path=os.path.join(OUT, "m09_today_dark.png"))
        print("404s:", missing)
        check(not [u for u in missing if not u.endswith("/favicon.ico")], "no missing files except the browser's favicon request")
        check(not errors, "no JavaScript errors" + (f": {errors[:3]}" if errors else ""))
        ctx.close()                                  # flushes the video file
        browser.close()
finally:
    srv.terminate()
print("ALL MOBILE TESTS PASSED" if not failures else f"{len(failures)} FAILED")
sys.exit(1 if failures else 0)
