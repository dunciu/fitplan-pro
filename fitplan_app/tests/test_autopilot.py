import asyncio
import datetime as dt
import json
import os
import tempfile
from types import SimpleNamespace as NS

os.environ["FITPLAN_MOCK"] = "1"
os.environ["FITPLAN_DB"] = os.path.join(tempfile.mkdtemp(), "ap.db")

from app import autopilot, db
from app.llm import AnthropicLLM, MockLLM
from app.pipeline import run_pipeline
from app.schemas import Profile

db.init()
PROFILE = Profile(goal="run a 10K", age=30, experience="beginner", weeks=8, days_per_week=4)


def make_plan(profile=PROFILE):
    async def go():
        return [e async for e in run_pipeline(profile, MockLLM())]
    final = asyncio.run(go())[-1]
    u = db.new_user()
    db.set_profile(u["id"], profile.model_dump(), {"level": "ok"})
    today = dt.date.today()
    start = today - dt.timedelta(days=today.weekday())
    db.save_plan(u["id"], start.isoformat(), final["framework"], final["weeks"], final["outline"], "initial")
    return u["id"], start


def session_on(uid, d):
    plan = db.active_plan(uid)
    start = dt.date.fromisoformat(plan["start_date"])
    wk = next(w for w in plan["weeks"] if w["week"] == (d - start).days // 7 + 1)
    return next((s for s in wk["sessions"] if s["day"] == autopilot.VALID_DAYS[d.weekday()]), None)


# Mock plan with 4 days/week: Mon easy, Tue quality, Thu easy, Sat long
def test_guardrails():
    uid, start = make_plan()
    tue = start + dt.timedelta(days=1)
    s = autopilot.Session(db.active_plan(uid), tue, 4)
    T = tue.isoformat()
    ok = lambda r: r["ok"]
    assert not ok(s.handle("ease_session", {"date": T, "type": "quality", "minutes": 999, "title": "x", "effort": "x", "details": []}))
    assert not ok(s.handle("ease_session", {"date": (start + dt.timedelta(days=5)).isoformat(), "type": "easy", "minutes": 20,
                                            "title": "x", "effort": "x", "details": []})), "outside the 2-day edit window"
    assert not ok(s.handle("ease_session", {"date": start.isoformat(), "type": "easy", "minutes": 10, "title": "x", "effort": "x",
                                            "details": []})), "past dates are locked"
    assert not ok(s.handle("move_session", {"from_date": T, "to_date": (start + dt.timedelta(days=3)).isoformat()})), "Thu has a session"
    assert not ok(s.handle("move_session", {"from_date": T, "to_date": (start + dt.timedelta(days=4)).isoformat()})), \
        "Fri would sit next to Saturday's long run"
    assert ok(s.handle("move_session", {"from_date": T, "to_date": (start + dt.timedelta(days=2)).isoformat()}))
    assert not ok(s.handle("ease_session", {"date": T, "type": "easy", "minutes": 10, "title": "x", "effort": "x", "details": []})), \
        "Tue is now empty"
    assert ok(s.handle("rest_day", {"date": (start + dt.timedelta(days=2)).isoformat()}))
    assert ok(s.handle("rest_day", {"date": (start + dt.timedelta(days=3)).isoformat()}))
    assert len(s.changes) == 3
    assert not ok(s.handle("rest_day", {"date": T})) and "Limit" in s.handle("rest_day", {"date": T})["error"]
    assert ok(s.handle("finish", {"message": "done"}))
    assert db.active_plan(uid)["version"] == 1, "the Session works on a copy; nothing is saved by the handler"


def test_sore_day_eases_hard_session_and_undo_restores():
    uid, start = make_plan()
    tue = start + dt.timedelta(days=1)
    before = dict(session_on(uid, tue))
    assert before["type"] == "quality"
    db.upsert_log(uid, tue.isoformat(), soreness=8, sleep_h=7.4)
    chk = autopilot.check(uid, tue)
    assert chk["triggered"] and "soreness 8/10" in chk["reasons"]
    res = asyncio.run(autopilot.run(uid, tue, MockLLM()))
    a = res["action"]
    assert res["acted"] and a["kind"] == "adjusted" and a["version_after"] == 2
    now = session_on(uid, tue)
    assert now["type"] == "easy" and now["minutes"] < before["minutes"] and now.get("autopilot")
    assert any(st["tool"] == "ease_session" and st["result"]["ok"] for st in a["steps"])
    assert asyncio.run(autopilot.run(uid, tue, MockLLM()))["reason"] == "already handled"
    assert autopilot.undo(uid, a["id"])["ok"]
    assert session_on(uid, tue)["type"] == "quality" and db.active_plan(uid)["version"] == 3
    assert not autopilot.undo(uid, a["id"])["ok"]


def test_no_trigger_no_action_and_toggle_off():
    uid, start = make_plan()
    tue = start + dt.timedelta(days=1)
    db.upsert_log(uid, tue.isoformat(), soreness=3, sleep_h=7.5, mood=4)
    assert not autopilot.check(uid, tue)["triggered"]
    assert asyncio.run(autopilot.run(uid, tue, MockLLM()))["reason"] == "no triggers"
    db.upsert_log(uid, tue.isoformat(), soreness=9)
    db.set_autopilot(uid, False)
    assert not autopilot.check(uid, tue)["triggered"]
    assert asyncio.run(autopilot.run(uid, tue, MockLLM()))["reason"] == "autopilot is off"


def test_hrv_and_rhr_triggers_use_personal_baseline():
    uid, start = make_plan()
    day = start + dt.timedelta(days=1)
    for i in range(7, 28):
        db.upsert_log(uid, (day - dt.timedelta(days=i)).isoformat(), hrv=70, rhr=55)
    db.upsert_log(uid, day.isoformat(), hrv=55, rhr=62)
    reasons = autopilot.check(uid, day)["reasons"]
    assert any(r.startswith("HRV 55") for r in reasons) and any(r.startswith("resting HR 62") for r in reasons)


def test_red_flag_note_escalates_without_touching_plan():
    uid, start = make_plan()
    tue = start + dt.timedelta(days=1)
    db.upsert_log(uid, tue.isoformat(), notes="felt chest pain on my warm-up")
    assert autopilot.check(uid, tue)["triggered"]
    res = asyncio.run(autopilot.run(uid, tue, MockLLM()))
    assert res["action"]["kind"] == "escalate" and "doctor" in res["action"]["message"].lower()
    assert db.active_plan(uid)["version"] == 1


def test_daily_pass_acts_without_the_app_open():
    uid, start = make_plan()
    sat = start + dt.timedelta(days=5)
    db.upsert_log(uid, sat.isoformat(), sleep_h=4.5)
    n = asyncio.run(autopilot.daily_pass(lambda: (MockLLM(), True), sat))
    assert n >= 1 and session_on(uid, sat)["type"] == "easy"


def test_real_tool_loop_sends_rejections_back_to_the_model():
    """AnthropicLLM.run_tools with a fake client: the model first asks for something the guardrails reject, gets the
    error back as a tool_result, then corrects itself and finishes."""
    uid, start = make_plan()
    tue = start + dt.timedelta(days=1)
    sess = autopilot.Session(db.active_plan(uid), tue, 4)
    T = tue.isoformat()
    script = [
        [NS(type="text", text="Soreness is high; I'll make Tuesday harder? No, easier."),
         NS(type="tool_use", id="t1", name="ease_session", input={"date": T, "type": "quality", "minutes": 999, "title": "x", "effort": "x", "details": []})],
        [NS(type="tool_use", id="t2", name="ease_session", input={"date": T, "type": "easy", "minutes": 20, "title": "Easy jog",
                                                                   "effort": "RPE 3", "details": ["20 min easy"]}),
         NS(type="tool_use", id="t3", name="finish", input={"message": "Eased Tuesday."})],
        [NS(type="text", text="should never be reached")],
    ]
    sent = []

    async def create(**kw):
        sent.append(json.loads(json.dumps(kw["messages"], default=str)))
        return NS(content=script[len(sent) - 1])

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.client = NS(messages=NS(create=create))
    steps = asyncio.run(llm.run_tools("SYS", "USER", autopilot.TOOLS, sess.handle))
    assert len(sent) == 2, "loop stops after finish"
    second_turn_results = sent[1][-1]["content"]
    assert second_turn_results[0]["type"] == "tool_result" and second_turn_results[0]["is_error"] is True
    assert "Minutes must be between" in json.loads(second_turn_results[0]["content"])["error"]
    assert [s["tool"] for s in steps] == ["thought", "ease_session", "ease_session", "finish"]
    assert sess.changes[0]["to"] == "easy 20 min" and sess.message == "Eased Tuesday."
