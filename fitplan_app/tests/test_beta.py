import asyncio
import datetime as dt
import io
import json
import os
import tempfile
import zipfile

os.environ["FITPLAN_MOCK"] = "1"
os.environ["FITPLAN_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")

from app import coach, db, demo, ingest
from app.adapt import adapt_user
from app.llm import MockLLM
from app.pipeline import run_pipeline
from app.planlint import lint_block
from app.schemas import Profile

db.init()


def test_csv_whoop_new_style_and_sanity():
    csv_text = ("Cycle start time,Recovery score %,Resting heart rate (bpm),Heart rate variability (ms),Asleep duration (min)\n"
                "2026-10-01 06:10:00,70,52,80,450\n2026-10-02 06:10:00,65,300,75,420\n2026-10-03 06:10:00,60,54,9999,30\n")
    r = ingest.parse_csv(csv_text)
    assert r["days"]["2026-10-01"] == {"hrv": 80.0, "rhr": 52.0, "sleep_h": 7.5}
    assert "rhr" not in r["days"]["2026-10-02"] and "hrv" not in r["days"]["2026-10-03"]
    assert r["dropped"] == 2   # 300 bpm and 9999 ms; the 30-minute sleep (0.5 h) is still in range


def test_csv_oura_seconds_and_fitbit_minutes():
    oura = "date,Average HRV,Lowest Heart Rate,Total Sleep Duration\n2026-10-01,60,50,27000\n2026-10-02,58,51,25200\n"
    assert abs(ingest.parse_csv(oura)["days"]["2026-10-01"]["sleep_h"] - 7.5) < 0.01
    fitbit = "date,resting_heart_rate,minutes_asleep,hrv_rmssd,steps\n2026-10-01,55,420,65,8000\n"
    d = ingest.parse_csv(fitbit)["days"]["2026-10-01"]
    assert d["sleep_h"] == 7.0 and d["steps"] == 8000


def test_csv_errors():
    for bad in ("", "a,b\n1,2\n", "date,foo\n2026-10-01,3\n"):
        try:
            ingest.parse_csv(bad)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def _apple_xml(day):
    return f"""<?xml version="1.0"?><HealthData>
<Record type="HKQuantityTypeIdentifierRestingHeartRate" value="54" endDate="{day} 08:00:00 +0100" startDate="{day} 08:00:00 +0100"/>
<Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" value="48" endDate="{day} 03:00:00 +0100" startDate="{day} 03:00:00 +0100"/>
<Record type="HKQuantityTypeIdentifierStepCount" value="4000" endDate="{day} 12:00:00 +0100" startDate="{day} 11:00:00 +0100"/>
<Record type="HKQuantityTypeIdentifierStepCount" value="3500" endDate="{day} 18:00:00 +0100" startDate="{day} 17:00:00 +0100"/>
<Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepCore" startDate="{day} 00:00:00 +0100" endDate="{day} 06:30:00 +0100"/>
<Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisInBed" startDate="{day} 00:00:00 +0100" endDate="{day} 07:00:00 +0100"/>
</HealthData>""".encode()


def test_apple_xml_and_zip():
    day = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    r = ingest.parse_upload(_apple_xml(day), "export.xml")
    row = r["days"][day]
    assert row["rhr"] == 54 and row["hrv"] == 48 and row["steps"] == 7500 and abs(row["sleep_h"] - 6.5) < 0.01
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("apple_health_export/export.xml", _apple_xml(day))
    assert ingest.parse_upload(buf.getvalue(), "export.zip")["days"][day]["rhr"] == 54


def _decision(scn, today=None):
    today = today or dt.date.today()
    rows = demo.seed(scn, today)
    logs = [dict(date=d, **r) for d, r in rows.items()]
    return coach.decide(coach.metrics(logs, today, {}))


def test_coach_scenarios():
    assert _decision("steady")[0] in ("progress", "maintain")
    assert _decision("illness")[0] == "rest_illness"
    assert _decision("poor_sleep")[0] in ("reduce_intensity", "deload")
    assert _decision("overreaching")[0] in ("deload", "reduce_intensity")


def test_upsert_log_merges():
    u = db.new_user()
    db.upsert_log(u["id"], "2026-10-01", sleep_h=7.0, source="manual")
    db.upsert_log(u["id"], "2026-10-01", soreness=4)
    row = db.get_logs(u["id"], "2026-10-01", "2026-10-01")[0]
    assert row["sleep_h"] == 7.0 and row["soreness"] == 4
    db.delete_user(u["id"])
    assert db.get_user(u["id"]) is None


def _make_plan(profile):
    async def go():
        return [e async for e in run_pipeline(profile, MockLLM())]
    final = asyncio.run(go())[-1]
    assert final["status"] == "ok"
    u = db.new_user()
    db.set_profile(u["id"], profile.model_dump(), {"level": "ok"})
    today = dt.date.today()
    start = today - dt.timedelta(days=today.weekday())
    db.save_plan(u["id"], start.isoformat(), final["framework"], final["weeks"], final["outline"], "initial")
    return u["id"]


def test_adapt_overreaching_creates_new_version_with_valid_week():
    p = Profile(goal="run a 10K", age=30, experience="beginner", weeks=8, days_per_week=4)
    uid = _make_plan(p)
    plan = db.active_plan(uid)
    rows = demo.seed("overreaching", dt.date.today(), coach.planned_sessions(plan["weeks"], plan["start_date"]))
    for d, r in rows.items():
        db.upsert_log(uid, d, **r)
    res = asyncio.run(adapt_user(uid, MockLLM()))
    assert res["ok"] and res["plan_changed"] and res["version"] == 2
    assert res["decision"] in ("deload", "reduce_intensity")
    new = db.active_plan(uid)
    row = next(r for r in new["outline"] if r["week"] == res["week"])
    wk = next(w for w in new["weeks"] if w["week"] == res["week"])
    assert row["adapted"] and not [m for s, m in lint_block([wk], [row], p) if s == "error"]
    assert all(s["type"] != "quality" for s in wk["sessions"])
    assert db.unseen_count(uid) == 1


def test_adapt_illness_cuts_days_and_volume():
    p = Profile(goal="run a 10K", age=30, experience="beginner", weeks=8, days_per_week=5)
    uid = _make_plan(p)
    plan = db.active_plan(uid)
    for d, r in demo.seed("illness", dt.date.today(), coach.planned_sessions(plan["weeks"], plan["start_date"])).items():
        db.upsert_log(uid, d, **r)
    res = asyncio.run(adapt_user(uid, MockLLM()))
    assert res["decision"] == "rest_illness"
    wk = next(w for w in db.active_plan(uid)["weeks"] if w["week"] == res["week"])
    assert len([s for s in wk["sessions"] if s["type"] != "mobility"]) <= 3
    assert res["new_minutes"] < res["old_minutes"]


def test_adapt_red_flag_note_pauses():
    p = Profile(goal="run a 10K", age=30, experience="beginner", weeks=8, days_per_week=4)
    uid = _make_plan(p)
    db.upsert_log(uid, dt.date.today().isoformat(), notes="I felt chest pain on my run")
    res = asyncio.run(adapt_user(uid, MockLLM()))
    assert res["decision"] == "pause_and_refer" and not res["plan_changed"]
    assert db.active_plan(uid)["version"] == 1
