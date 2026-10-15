"""Weekly adaptation: logs -> deterministic decision (coach.py) -> rebuild NEXT week's sessions with the research
agent's session builder (machine-checked) -> new plan version + a check-in message for the person."""
import datetime as dt
import json

from . import coach, db
from .pipeline import _build_block, _constraints_block, _profile_block
from .safety import screen, screen_with_model
from .schemas import Profile
from .targets import facts

RULES = {
    "progress": "Follow the planned progression.",
    "maintain": "Hold the load; do not progress this week.",
    "reduce_intensity": "Keep the time but make every session easy: NO quality (hard) sessions this week.",
    "deload": "Recovery week: all sessions easy and shorter, no quality sessions.",
    "rest_illness": "The person may be ill. Only a few short, very easy sessions, and only if they feel well; otherwise rest. No quality sessions.",
}


def iso_week(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _r5(x: float) -> int:
    return int(round(x / 5.0) * 5)


def _adjust_row(decision: str, cur: dict, nxt: dict, days: int) -> tuple[dict, int]:
    row, d = dict(nxt), days
    if decision == "progress":
        pass
    elif decision == "maintain":
        row["minutes"] = nxt["minutes"] if (nxt["deload"] or nxt["taper"]) else cur["minutes"]
    elif decision == "reduce_intensity":
        row["minutes"], row["no_quality"] = _r5(0.9 * nxt["minutes"]), True
    elif decision == "deload":
        row.update(minutes=_r5(0.6 * cur["minutes"]), no_quality=True, phase="Deload (adapted)", deload=True)
    elif decision == "rest_illness":
        d = min(3, days)
        row.update(minutes=_r5(0.35 * cur["minutes"]), no_quality=True, phase="Return from illness", deload=True)
    row["adapted"], row["decision"] = True, decision
    return row, d


def _markdown(decision: str, reasons: list[str], mt: dict, week: int, old: int | None, new: int | None, note: str = "") -> str:
    out = [f"**{coach.LABELS.get(decision, decision)}** (planning week {week})", ""]
    out.append("Why: " + "; ".join(reasons) + ("" if reasons[-1].endswith(".") else "."))
    out += ["", "What I looked at (last 7 days vs your own baseline):"] + [f"- {m}" for m in coach.fmt_metrics(mt)]
    if old is not None and new is not None:
        out += ["", f"Next week's target time: {old} -> {new} min." + (f" {note}" if note else "")]
    out += ["", "This is coaching guidance, not medical advice."]
    return "\n".join(out)


async def adapt_user(uid: int, llm, today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    user, plan = db.get_user(uid), db.active_plan(uid)
    if not user or not user.get("profile") or not plan:
        return {"ok": False, "error": "No plan yet. Create one first."}
    profile = Profile.model_validate(json.loads(user["profile"]))
    start = dt.date.fromisoformat(plan["start_date"])
    wi, n = (today - start).days // 7, len(plan["outline"])
    if wi < 0:
        return {"ok": False, "error": "Your plan hasn't started yet."}
    planned = coach.planned_sessions(plan["weeks"], plan["start_date"])
    logs = db.get_logs(uid, (today - dt.timedelta(days=27)).isoformat(), today.isoformat())
    mt = coach.metrics(logs, today, planned)

    # Safety re-screen on anything the person wrote in the last 7 days
    notes = " ".join(l["notes"] for l in logs[-7:] if l.get("notes"))
    noted = profile.model_copy(update={"notes": f"{profile.notes} {notes}"[:800]})
    try:
        sc = await screen_with_model(noted, llm)
    except Exception:
        sc = screen(noted)
    if sc.level == "hold":
        md = _markdown("pause_and_refer", [sc.message], mt, wi + 2, None, None)
        cid = db.add_checkin(uid, wi, "pause_and_refer", {"reasons": [sc.message], "metrics": coach.fmt_metrics(mt)}, md)
        db.set_last_adapt(uid, iso_week(today))
        return {"ok": True, "decision": "pause_and_refer", "reasons": [sc.message], "checkin_id": cid, "plan_changed": False}

    if wi + 1 >= n:
        md = "**Plan complete.** You've reached the end of this plan. Create a new one from Settings when you're ready.\n\nThis is coaching guidance, not medical advice."
        cid = db.add_checkin(uid, wi, "complete", {"reasons": ["end of plan"], "metrics": coach.fmt_metrics(mt)}, md)
        return {"ok": True, "decision": "complete", "reasons": ["end of plan"], "checkin_id": cid, "plan_changed": False}

    decision, reasons = coach.decide(mt)
    cur, nxt = plan["outline"][wi], plan["outline"][wi + 1]
    row, days = _adjust_row(decision, cur, nxt, profile.days_per_week)
    p2 = profile.model_copy(update={"days_per_week": days})
    s0 = screen(profile)
    base = f"{_profile_block(p2)}\n\n{_constraints_block(s0)}\n\n{facts(p2, s0)}"
    prev = next((w for w in plan["weeks"] if w["week"] == cur["week"]), None)
    prev_txt = "; ".join(f"{x['day']} {x['type']} {x['minutes']}min" for x in prev["sessions"]) if prev else "n/a"
    feedback = (f"WEEKLY ADAPTATION for week {row['week']}. Decision: {decision}. Why: {'; '.join(reasons)}. "
                f"{RULES[decision]} Last week's sessions: {prev_txt}. Keep continuity with the framework's exercises.")
    weeks, issues, _ = await _build_block(llm, base, plan["framework"], p2, [row], feedback)
    errors = [m for sev, m in issues if sev == "error"]

    new_weeks = sorted([w for w in plan["weeks"] if w["week"] != row["week"]] + list(weeks), key=lambda w: w["week"])
    new_outline = [row if r["week"] == row["week"] else r for r in plan["outline"]]
    version = db.save_plan(uid, plan["start_date"], plan["framework"], new_weeks, new_outline, note=decision)
    md = _markdown(decision, reasons, mt, row["week"], nxt["minutes"], row["minutes"],
                   "Some automated checks still flagged this week, so give it a quick read." if errors else "")
    cid = db.add_checkin(uid, wi, decision, {"reasons": reasons, "metrics": coach.fmt_metrics(mt),
                                              "old_minutes": nxt["minutes"], "new_minutes": row["minutes"]}, md)
    db.set_last_adapt(uid, iso_week(today))
    return {"ok": True, "decision": decision, "reasons": reasons, "checkin_id": cid, "plan_changed": True,
            "version": version, "week": row["week"], "old_minutes": nxt["minutes"], "new_minutes": row["minutes"]}
