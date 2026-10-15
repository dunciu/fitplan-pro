"""Autopilot: an autonomous daily agent that reacts to a bad day (soreness, short sleep, HRV drop, resting-HR spike,
low mood) by changing the next few sessions itself, then tells the person what it did and why.

Division of labour:
  - code decides IF to act (deterministic triggers) and runs the safety screen first;
  - Claude decides HOW, by calling tools (ease_session, move_session, rest_day, finish);
  - code enforces guardrails on every tool call: the agent can only make training easier, only touch the next
    few days, at most 3 changes, and every change is versioned so the person can undo it.
Triggered by a check-in, a data import, or the daily morning pass in the scheduler.
"""
import copy
import datetime as dt
import hashlib
import json

from . import coach, db
from .planlint import VALID_DAYS
from .safety import screen, screen_with_model
from .schemas import Profile

RANK = {"mobility": 0, "easy": 1, "cross": 1, "strength": 2, "skill": 2, "long": 2, "quality": 3}
HARD = ("quality", "long")
EDIT_DAYS, MOVE_DAYS, MAX_CHANGES = 2, 4, 3

SYSTEM = """You are the AUTOPILOT agent of FitPlan Pro. The person's check-in or wearable data shows a tough day. Adjust
their next few sessions so they recover, using the tools. You act on your own; the person is told afterwards and can undo.

Rules (enforced by the tools; a rejected call returns the reason so you can try something else):
- You may only make training easier: lower minutes, a gentler session type, move a hard session later, or a rest day.
- Only sessions from today up to 2 days ahead can be changed. Moves must stay in the same plan week and go later.
- At most 3 changes. Make the smallest change that fits the signals: one bad night -> ease today only; high soreness or
  a big HRV drop -> ease or move the hard sessions in the window; signs of illness -> rest days.
- Do not diagnose. If something sounds medical, say so in the finish message and suggest a clinician.
Finish by calling `finish` with 2-3 friendly sentences to the person: what changed, why (quote their numbers), and that
they can undo it if they feel fine."""

TOOLS = [
    {"name": "ease_session", "description": "Make one upcoming session easier (lower minutes and/or gentler type).",
     "input_schema": {"type": "object", "properties": {
         "date": {"type": "string", "description": "YYYY-MM-DD of an existing session"},
         "type": {"type": "string", "enum": ["easy", "mobility", "cross", "strength", "skill", "long", "quality"]},
         "minutes": {"type": "integer"}, "title": {"type": "string"}, "effort": {"type": "string"},
         "details": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string"}},
         "required": ["date", "type", "minutes", "title", "effort", "details"]}},
    {"name": "move_session", "description": "Move a session to a later rest day in the same plan week.",
     "input_schema": {"type": "object", "properties": {"from_date": {"type": "string"}, "to_date": {"type": "string"},
                                                       "why": {"type": "string"}}, "required": ["from_date", "to_date"]}},
    {"name": "rest_day", "description": "Replace a session with rest.",
     "input_schema": {"type": "object", "properties": {"date": {"type": "string"}, "why": {"type": "string"}}, "required": ["date"]}},
    {"name": "finish", "description": "End and send a short message to the person explaining the changes.",
     "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}},
]


# --- triggers --------------------------------------------------------------------------------------------------
def triggers(log: dict | None, mt: dict) -> list[str]:
    if not log:
        return []
    out = []
    if (log.get("soreness") or 0) >= 7:
        out.append(f"soreness {log['soreness']}/10")
    if log.get("sleep_h") is not None and log["sleep_h"] < 6:
        out.append(f"only {log['sleep_h']:.1f} h sleep")
    if log.get("rhr") is not None and mt.get("rhr_base") and log["rhr"] - mt["rhr_base"] >= 5:
        out.append(f"resting HR {log['rhr']:.0f} bpm ({log['rhr'] - mt['rhr_base']:+.0f} vs baseline)")
    if log.get("hrv") is not None and mt.get("hrv_base") and log["hrv"] / mt["hrv_base"] - 1 <= -0.15:
        out.append(f"HRV {log['hrv']:.0f} ms ({log['hrv'] / mt['hrv_base'] - 1:+.0%} vs baseline)")
    if log.get("mood") == 1:
        out.append("low mood")
    return out


def _context(uid: int, day: dt.date):
    plan = db.active_plan(uid)
    if not plan:
        return None
    logs = db.get_logs(uid, (day - dt.timedelta(days=27)).isoformat(), day.isoformat())
    planned = coach.planned_sessions(plan["weeks"], plan["start_date"])
    mt = coach.metrics(logs, day, planned)
    log = next((l for l in logs if l["date"] == day.isoformat()), None)
    return plan, mt, log


def check(uid: int, day: dt.date) -> dict:
    """Cheap, no model: would the autopilot act today?"""
    ctx = _context(uid, day)
    if not ctx or not db.autopilot_on(uid):
        return {"triggered": False, "reasons": []}
    plan, mt, log = ctx
    if log and log.get("notes"):
        user = db.get_user(uid)
        p = Profile.model_validate(json.loads(user["profile"]))
        if screen(p.model_copy(update={"notes": f"{p.notes} {log['notes']}"[:800]})).level == "hold":
            return {"triggered": True, "reasons": ["a health warning sign in your note"]}
    r = triggers(log, mt)
    # A note the keyword layer didn't flag still goes to the Claude safety classifier inside run().
    return {"triggered": bool(r), "reasons": r, "screen_note": bool(log and log.get("notes")) and not r}


# --- guarded tool execution --------------------------------------------------------------------------------------
class Session:
    def __init__(self, plan: dict, day: dt.date, days_per_week: int):
        self.start = dt.date.fromisoformat(plan["start_date"])
        self.weeks = copy.deepcopy(plan["weeks"])
        self.day, self.dpw, self.changes, self.message = day, days_per_week, [], ""

    def _loc(self, date: str):
        d = dt.date.fromisoformat(date)
        w, wd = (d - self.start).days // 7 + 1, VALID_DAYS[d.weekday()]
        return d, w, wd, next((x for x in self.weeks if x["week"] == w), None)

    def _session(self, date: str):
        d, w, wd, wk = self._loc(date)
        s = next((x for x in (wk or {}).get("sessions", []) if x.get("day") == wd and x.get("type") != "mobility"), None)
        return d, wk, s

    def upcoming(self) -> list[dict]:
        out = []
        for i in range(EDIT_DAYS + 1):
            date = (self.day + dt.timedelta(days=i)).isoformat()
            _, _, s = self._session(date)
            if s:
                out.append({"date": date, "day": s["day"], "type": s["type"], "title": s.get("title"), "minutes": s.get("minutes"),
                            "effort": s.get("effort")})
        return out

    def _window(self, d: dt.date, days: int):
        if not (self.day <= d <= self.day + dt.timedelta(days=days)):
            return f"Only dates from {self.day} to {self.day + dt.timedelta(days=days)} can be changed."
        return None

    def _adjacent_hard(self, wk: dict, day_name: str, exclude=None) -> bool:
        i = VALID_DAYS.index(day_name)
        for s in wk["sessions"]:
            if s is exclude or s.get("type") not in HARD or s.get("day") not in VALID_DAYS:
                continue
            if abs(VALID_DAYS.index(s["day"]) - i) == 1:
                return True
        return False

    def handle(self, name: str, inp: dict) -> dict:
        try:
            if name == "finish":
                self.message = str(inp.get("message", ""))[:600]
                return {"ok": True}
            if len(self.changes) >= MAX_CHANGES:
                return {"ok": False, "error": f"Limit of {MAX_CHANGES} changes reached. Call finish."}
            if name == "ease_session":
                d, wk, s = self._session(inp["date"])
                if err := self._window(d, EDIT_DAYS):
                    return {"ok": False, "error": err}
                if not s:
                    return {"ok": False, "error": "No session on that date."}
                new_t, mins = inp["type"], int(inp["minutes"])
                if new_t not in RANK or RANK[new_t] > RANK.get(s["type"], 3):
                    return {"ok": False, "error": f"Type {new_t} is harder than the planned {s['type']}. Choose a gentler type."}
                if mins > int(s.get("minutes", 0)) or mins < 5:
                    return {"ok": False, "error": f"Minutes must be between 5 and the planned {s.get('minutes')}."}
                before = dict(s)
                s.update(type=new_t, minutes=mins, title=str(inp["title"])[:80], effort=str(inp["effort"])[:120],
                         details=[str(x)[:160] for x in inp.get("details", [])][:6] or s.get("details", []),
                         why=str(inp.get("why", "Adjusted by your coach"))[:200], autopilot=True)
                self.changes.append({"kind": "eased", "date": inp["date"], "from": f"{before['type']} {before.get('minutes')} min",
                                     "to": f"{new_t} {mins} min", "title": s["title"]})
                return {"ok": True, "now": f"{new_t} {mins} min"}
            if name == "move_session":
                d1, wk1, s = self._session(inp["from_date"])
                d2, w2, wd2, wk2 = self._loc(inp["to_date"])
                if err := (self._window(d1, EDIT_DAYS) or self._window(d2, MOVE_DAYS)):
                    return {"ok": False, "error": err}
                if not s:
                    return {"ok": False, "error": "No session on the from_date."}
                if wk2 is not wk1 or d2 <= d1:
                    return {"ok": False, "error": "Moves must go to a later day in the same plan week."}
                if any(x.get("day") == wd2 and x.get("type") != "mobility" for x in wk1["sessions"]):
                    return {"ok": False, "error": f"{inp['to_date']} already has a session. Pick a rest day."}
                if s["type"] in HARD and self._adjacent_hard(wk1, wd2, exclude=s):
                    return {"ok": False, "error": "That would put two hard sessions on consecutive days."}
                old_day = s["day"]
                s.update(day=wd2, autopilot=True, why=str(inp.get("why", s.get("why", "")))[:200])
                self.changes.append({"kind": "moved", "date": inp["from_date"], "from": old_day, "to": f"{wd2} {inp['to_date']}",
                                     "title": s.get("title")})
                return {"ok": True}
            if name == "rest_day":
                d, wk, s = self._session(inp["date"])
                if err := self._window(d, EDIT_DAYS):
                    return {"ok": False, "error": err}
                if not s:
                    return {"ok": False, "error": "No session on that date."}
                wk["sessions"].remove(s)
                self.changes.append({"kind": "rest", "date": inp["date"], "from": f"{s['type']} {s.get('minutes')} min",
                                     "to": "rest", "title": s.get("title")})
                return {"ok": True}
            return {"ok": False, "error": f"Unknown tool {name}."}
        except (KeyError, TypeError, ValueError) as e:
            return {"ok": False, "error": f"Bad input: {e}"}


def _signature(reasons: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(reasons)).encode()).hexdigest()[:12]


async def run(uid: int, day: dt.date, llm, force: bool = False) -> dict:
    """Run the autopilot for one person and day. Idempotent per day unless the triggers change."""
    ctx = _context(uid, day)
    if not ctx:
        return {"acted": False, "reason": "no plan"}
    if not db.autopilot_on(uid) and not force:
        return {"acted": False, "reason": "autopilot is off"}
    plan, mt, log = ctx
    user = db.get_user(uid)
    profile = Profile.model_validate(json.loads(user["profile"]))
    date = day.isoformat()

    # 1. Safety first, in code: a red flag in today's note -> no training advice, refer.
    if log and log.get("notes"):
        noted = profile.model_copy(update={"notes": f"{profile.notes} {log['notes']}"[:800]})
        try:
            sc = await screen_with_model(noted, llm)
        except Exception:
            sc = screen(noted)
        if sc.level == "hold":
            sig = _signature(["hold"] + sc.flags)
            if any(a["signature"] == sig for a in db.list_actions(uid, date=date)):
                return {"acted": False, "reason": "already handled"}
            aid = db.add_action(uid, date, "escalate", sig, sc.flags, [], sc.message, plan["version"], plan["version"])
            return {"acted": True, "action": db.get_action(uid, aid)}

    reasons = triggers(log, mt)
    if not reasons:
        return {"acted": False, "reason": "no triggers"}
    sig = _signature(reasons)
    if any(a["signature"] == sig and not a["undone"] for a in db.list_actions(uid, date=date)):
        return {"acted": False, "reason": "already handled"}

    sess = Session(plan, day, profile.days_per_week)
    upcoming = sess.upcoming()
    if not upcoming:
        return {"acted": False, "reason": "no sessions in the next few days"}

    # 2. Claude decides how, through guarded tools.
    user_msg = (f"TODAY: {date} ({VALID_DAYS[day.weekday()]})\nSIGNALS TODAY: {'; '.join(reasons)}\n"
                f"LAST 7 DAYS vs BASELINE: {'; '.join(coach.fmt_metrics(mt))}\n"
                f"PERSON: goal '{profile.goal}', {profile.experience}, age {profile.age}, injuries: {profile.injuries or 'none'}\n"
                f"UPCOMING SESSIONS (only these can change):\n{json.dumps(upcoming, indent=1)}\n"
                f"Rest days you could move to (same week, later): "
                f"{[(day + dt.timedelta(days=i)).isoformat() for i in range(1, MOVE_DAYS + 1) if not sess._session((day + dt.timedelta(days=i)).isoformat())[2]]}")
    steps = await llm.run_tools(SYSTEM, user_msg, TOOLS, sess.handle, max_turns=8, context={"upcoming": upcoming})

    if not sess.changes:
        aid = db.add_action(uid, date, "no_change", sig, reasons, steps,
                            sess.message or "I looked at today's signals and kept your plan as it is.", plan["version"], plan["version"])
        return {"acted": True, "action": db.get_action(uid, aid)}
    after = db.save_plan(uid, plan["start_date"], plan["framework"], sess.weeks, plan["outline"], note="autopilot")
    msg = sess.message or "I eased your next session because of today's signals. Undo it if you feel fine."
    steps.append({"tool": "changes", "input": sess.changes, "result": None})
    aid = db.add_action(uid, date, "adjusted", sig, reasons, steps, msg, plan["version"], after)
    return {"acted": True, "action": db.get_action(uid, aid)}


def undo(uid: int, aid: int) -> dict:
    a = db.get_action(uid, aid)
    if not a:
        return {"ok": False, "error": "Not found."}
    if a["undone"] or a["version_before"] == a["version_after"]:
        return {"ok": False, "error": "Nothing to undo."}
    cur = db.active_plan(uid)
    if cur["version"] != a["version_after"]:
        return {"ok": False, "error": "Your plan has changed since then, so this can't be undone safely."}
    prev = db.plan_version(uid, a["version_before"])
    v = db.save_plan(uid, prev["start_date"], prev["framework"], prev["weeks"], prev["outline"], note="undo autopilot")
    db.mark_undone(aid)
    return {"ok": True, "version": v}


async def daily_pass(get_llm_fn, day: dt.date) -> int:
    """Called by the scheduler each morning: act for everyone whose data for today already shows a tough day,
    without them opening the app."""
    n = 0
    for u in db.users_with_plans():
        try:
            if check(u["id"], day)["triggered"]:
                llm, _ = get_llm_fn()
                res = await run(u["id"], day, llm)
                db.log_run(u["id"], "autopilot_daily", "acted" if res.get("acted") else "skipped", res.get("reason", ""))
                n += 1
        except Exception as e:
            db.log_run(u["id"], "autopilot_daily", "error", str(e))
    return n
