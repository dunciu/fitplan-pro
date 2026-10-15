"""Live HTTP smoke test of the phone API (mock LLM). Needs: uvicorn, starlette, requests.
Run:  python tests/smoke_http.py"""
import json
import os
import subprocess
import sys
import tempfile
import time

import requests

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
env = dict(os.environ, FITPLAN_MOCK="1", FITPLAN_DB=os.path.join(tempfile.mkdtemp(), "smoke.db"))
srv = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory", "app.beta_api:build_app", "--port", str(PORT), "--log-level", "warning"],
                       env=env, cwd=os.path.join(os.path.dirname(__file__), ".."))
try:
    for _ in range(50):
        try:
            requests.get(BASE + "/health", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise SystemExit("server did not start")

    ok = lambda cond, msg: (print(("PASS " if cond else "FAIL ") + msg), cond or sys.exit(1))
    ok(requests.get(BASE + "/health").json()["mock_mode"] is True, "health in mock mode")
    ok(requests.get(BASE + "/me").status_code == 401, "no token -> 401")
    tok = requests.post(BASE + "/session").json()["token"]
    H = {"X-User-Token": tok}
    ok(requests.get(BASE + "/me", headers=H).json()["plan"] is None, "new user has no plan")

    bad = requests.post(BASE + "/onboard", headers=H, json={"goal": "x", "age": 2})
    ok(bad.status_code == 422, "invalid profile -> 422")

    r = requests.post(BASE + "/onboard", headers=H, stream=True,
                      json={"goal": "run a 10K", "age": 30, "experience": "beginner", "weeks": 8, "days_per_week": 4})
    evs = [json.loads(l[6:]) for l in r.iter_lines(decode_unicode=True) if l and l.startswith("data: ")]
    stages = [e["stage"] for e in evs]
    ok("draft" in stages and stages.index("draft") < stages.index("critic"), "draft plan arrives before the review")
    ok(evs[-1]["stage"] == "final" and evs[-1]["status"] == "ok" and evs[-1]["version"] == 2, "reviewed plan saved as v2")
    ok(evs[-1]["report"]["checks"]["final_errors"] == 0 and "timings_s" in evs[-1]["report"], "final event carries a quality report")
    ok(requests.get(BASE + "/onboard/status", headers=H).json()["running"] is False, "job status reports finished")
    t3 = requests.post(BASE + "/session").json()["token"]
    H3 = {"X-User-Token": t3}
    st = requests.post(BASE + "/onboard?nostream=1", headers=H3, json={"goal": "swim 1500 m", "age": 33, "weeks": 8, "days_per_week": 3})
    ok(st.status_code == 202, "phone-style plan start returns immediately")
    for _ in range(40):
        if not requests.get(BASE + "/onboard/status", headers=H3).json()["running"]:
            break
        time.sleep(0.25)
    ok(requests.get(BASE + "/me", headers=H3).json()["plan"]["weeks"] == 8, "plan finished in the background without a stream")
    pl = requests.get(BASE + "/plan", headers=H).json()
    ok(pl["status"] == "reviewed" and pl["report"]["weeks"] == 8, "/plan includes status and report")
    ok(requests.post(BASE + "/plan/rate", headers=H, json={"rating": 1}).json()["ok"], "plan can be rated")
    ok(requests.post(BASE + "/plan/rate", headers=H, json={"rating": 5}).status_code == 422, "bad rating -> 422")

    me = requests.get(BASE + "/me", headers=H).json()
    ok(me["plan"]["weeks"] == 8 and me["profile"]["goal"] == "run a 10K", "/me shows plan and profile")
    plan = requests.get(BASE + "/plan", headers=H).json()
    ok(len(plan["weeks"]) == 8 and "{{WEEKLY_PLAN}}" not in plan["framework"], "/plan returns weeks and clean framework")
    td = requests.get(BASE + "/today", headers=H).json()
    ok(td["has_plan"] and td["week"] == 1 and len(td["strip"]) == 7, "/today returns week strip")

    ok(requests.post(BASE + "/log", headers=H, json={"sleep_h": 99}).status_code == 422, "implausible log -> 422")
    lg = requests.post(BASE + "/log", headers=H, json={"sleep_h": 7.2, "rhr": 54, "hrv": 68, "soreness": 3, "done": 1})
    ok(lg.json()["log"]["sleep_h"] == 7.2, "log saved")

    csv = "date,resting_heart_rate,minutes_asleep,hrv_rmssd,steps\n2026-09-20,55,420,65,8000\n2026-09-21,56,400,64,9000\n"
    up = requests.post(BASE + "/upload?filename=fitbit.csv", headers=H, data=csv.encode())
    ok(up.json()["imported_days"] == 2, "CSV upload imports 2 days")
    ok(requests.post(BASE + "/upload?filename=x.csv", headers=H, data=b"nonsense").status_code == 422, "bad upload -> 422")

    ok(requests.post(BASE + "/demo/seed", headers=H, json={"scenario": "nope"}).status_code == 400, "unknown demo scenario -> 400")
    ok(requests.post(BASE + "/demo/seed", headers=H, json={"scenario": "overreaching"}).json()["days"] == 28, "demo data seeded")
    tr = requests.get(BASE + "/trends", headers=H).json()
    ok(tr["readiness"] in ("green", "yellow", "red") and len(tr["series"]["hrv"]) == 28, "/trends returns series and readiness")

    ad = requests.post(BASE + "/adapt", headers=H, json={})
    ok(ad.status_code == 200 and ad.json()["plan_changed"] and ad.json()["version"] == 3, "adapt creates plan v3: " + ad.json().get("decision", "?"))
    ci = requests.get(BASE + "/checkins", headers=H).json()["items"]
    ok(len(ci) == 1 and ci[0]["seen"] == 0 and requests.get(BASE + "/me", headers=H).json()["unseen"] == 1, "check-in inbox has 1 unseen")
    requests.post(BASE + "/checkins/seen", headers=H)
    ok(requests.get(BASE + "/me", headers=H).json()["unseen"] == 0, "check-ins marked seen")

    ok("answer" in requests.post(BASE + "/ask", headers=H, json={"question": "What if I miss a week?"}).json(), "ask returns answer")
    held = requests.post(BASE + "/ask", headers=H, json={"question": "I get chest pain when I run, should I continue?"}).json()
    ok("doctor" in held["answer"].lower(), "ask with red flag defers to a doctor")

    # autopilot: a sore check-in triggers it, it adjusts, the action shows on /today, undo restores
    import datetime as _dt
    plan_now = requests.get(BASE + "/plan", headers=H).json()
    start = _dt.date.fromisoformat(plan_now["start_date"])
    tue = (start + _dt.timedelta(days=1)).isoformat()
    lg = requests.post(BASE + f"/log?date={tue}", headers=H, json={"date": tue, "soreness": 8}).json()
    ok(lg["autopilot"]["triggered"] and "soreness 8/10" in lg["autopilot"]["reasons"], "sore check-in triggers autopilot")
    ap = requests.post(BASE + "/autopilot", headers=H, json={"date": tue}).json()
    ok(ap["acted"] and ap["action"]["kind"] == "adjusted", "autopilot adjusted the plan")
    td = requests.get(BASE + f"/today?date={tue}", headers=H).json()
    ok(td["action"]["id"] == ap["action"]["id"] and td["session"]["type"] == "easy", "/today shows the eased session and the action")
    ok(requests.post(BASE + "/autopilot", headers=H, json={"date": tue}).json()["reason"] == "already handled", "autopilot is idempotent")
    ok(requests.post(BASE + "/actions/undo", headers=H, json={"id": ap["action"]["id"]}).json()["ok"], "undo works")
    ok(requests.get(BASE + f"/today?date={tue}", headers=H).json()["session"]["type"] == "quality", "session restored to quality after undo")
    ok(len(requests.get(BASE + "/actions", headers=H).json()["items"]) == 1, "activity feed lists the action")
    ok(requests.post(BASE + "/settings", headers=H, json={"autopilot": False}).json()["autopilot"] is False, "autopilot can be turned off")
    ok(requests.post(BASE + "/actions/undo", headers=H, json={}).status_code == 400, "undo without id -> 400")

    # live sync: push with the user's sync key, wrong key rejected, autopilot reacts to a short night
    info = requests.get(BASE + "/sync/info", headers=H).json()
    ok(info["push_key"].startswith("fps_") and info["push_url"].endswith("/api/v2/sync/push") and info["whoop"]["configured"] is False,
       "sync info returns push URL and key")
    ok(requests.post(BASE + "/sync/push", headers={"Authorization": "Bearer nope"}, json={"days": []}).status_code == 401, "wrong sync key -> 401")
    requests.post(BASE + "/settings", headers=H, json={"autopilot": True})
    today_s = _dt.date.today().isoformat()
    hae = {"data": {"metrics": [{"name": "sleep_analysis", "units": "hr", "data": [{"date": today_s, "totalSleep": 4.4}]},
                                {"name": "resting_heart_rate", "units": "count/min", "data": [{"date": today_s + " 06:00:00 +0100", "qty": 56}]}]}}
    pr = requests.post(BASE + "/sync/push", headers={"Authorization": "Bearer " + info["push_key"]}, json=hae).json()
    ok(pr["imported_days"] == 1 and pr["autopilot"]["triggered"], "Health Auto Export push imported and triggered the autopilot")
    acted = False
    for _ in range(20):
        if any(a["date"] == today_s for a in requests.get(BASE + "/actions", headers=H).json()["items"]):
            acted = True
            break
        time.sleep(0.25)
    ok(acted, "autopilot acted in the background after the push")
    ok(requests.post(BASE + "/connect/whoop/start", headers=H).status_code == 400, "WHOOP start explains it is not configured")
    ok(requests.post(BASE + "/sync/push", headers={"Authorization": "Bearer " + info["push_key"]}, json={"x": 1}).status_code == 422, "bad payload -> 422")

    # pairing: a second device claims the same account with a one-time code
    code = requests.post(BASE + "/pair/create", headers=H).json()["code"]
    phone_tok = requests.post(BASE + "/pair/claim", json={"code": code}).json()["token"]
    ok(phone_tok == tok and requests.get(BASE + "/me", headers={"X-User-Token": phone_tok}).json()["plan"] is not None, "pairing code links a second device")
    ok(requests.post(BASE + "/pair/claim", json={"code": code}).status_code == 400, "pairing code is single use")
    ok(requests.post(BASE + "/connect/google/start", headers=H).status_code == 400, "Google Health start explains it is not configured")
    ok(requests.post(BASE + "/connect/nope/start", headers=H).status_code == 404, "unknown provider -> 404")
    info2 = requests.get(BASE + "/sync/info", headers=H).json()
    ok(set(info2["connections"]) == {"whoop", "google"} and info2["sync_minutes"] == 60, "sync info lists both providers")

    other = requests.post(BASE + "/session").json()["token"]
    ok(requests.get(BASE + "/plan", headers={"X-User-Token": other}).status_code == 404, "other users can't see my plan")
    ok(requests.delete(BASE + "/me", headers=H).status_code == 200 and requests.get(BASE + "/me", headers=H).status_code == 401, "delete my data")
    print("ALL SMOKE TESTS PASSED")
finally:
    srv.terminate()
