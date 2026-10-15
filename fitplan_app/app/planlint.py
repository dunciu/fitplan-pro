"""Deterministic plan structure: weekly volume outline, session-block parsing, automated checks, rendering.

The LLM writes the *sessions*; code owns the *numbers* (weekly minutes, deloads, taper) and verifies the result,
so the consistency mistakes a draft can contain (wrong number of days, long run too big a share, taper that
doesn't match) are caught by code instead of relying on a model to notice.
"""
import json
import re

COUNTED = {"easy", "quality", "long", "strength", "cross", "skill"}
VALID_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
EVENT_WORDS = ("marathon", "half", "10k", "5k", "race", "triathlon", "event", "competition")
ENDURANCE_WORDS = ("run", "marathon", "10k", "5k", "swim", "triathlon", "cycl", "bike", "row")
BLOCK_WEEKS = 4


def is_event(goal: str) -> bool:
    g = goal.lower()
    return any(w in g for w in EVENT_WORDS)


def is_endurance(goal: str) -> bool:
    g = goal.lower()
    return any(w in g for w in ENDURANCE_WORDS)


def outline(p) -> list[dict]:
    """Week-by-week target minutes. Build weeks grow ~8% (6% for under-18 / 60+), every 4th week is a deload
    (75% of the last build week), and event goals taper (85% then 60% of peak) in the final two weeks."""
    per = {"beginner": 35, "intermediate": 50, "advanced": 60}.get(p.experience.strip().lower(), 40)
    growth = 0.06 if (p.age < 18 or p.age >= 60) else 0.08
    cap = p.days_per_week * per * 2
    n, event = p.weeks, is_event(p.goal)
    endur = is_endurance(p.goal) or event
    names = ("Base", "Build", "Peak") if endur else ("Foundation", "Build", "Intensify")
    rows, build, peak = [], 0.0, 0.0
    for w in range(1, n + 1):
        taper = event and n >= 8 and w >= n - 1
        deload = (w % 4 == 0) and not taper and w != n
        if not deload and not taper:
            build = p.days_per_week * per if w == 1 else min(build * (1 + growth), cap)
            peak = max(peak, build)
            minutes = build
            phase = names[0] if w <= n / 3 else names[1] if w <= 2 * n / 3 else names[2]
        elif deload:
            minutes, phase = 0.75 * build, "Deload"
        else:
            minutes, phase = (0.6 if w == n else 0.85) * peak, "Taper"
        rows.append(dict(week=w, phase=phase, minutes=int(round(minutes / 5.0) * 5), deload=deload, taper=taper))
    return rows


BLOCK_TOOL = {
    "name": "submit_weeks",
    "description": "Submit the training sessions for the requested weeks.",
    "input_schema": {"type": "object", "properties": {"weeks": {"type": "array", "items": {"type": "object", "properties": {
        "week": {"type": "integer"}, "focus": {"type": "string"}, "notes": {"type": "string"},
        "sessions": {"type": "array", "items": {"type": "object", "properties": {
            "day": {"type": "string", "enum": VALID_DAYS},
            "type": {"type": "string", "enum": ["easy", "quality", "long", "strength", "cross", "skill", "mobility"]},
            "title": {"type": "string"}, "minutes": {"type": "integer"}, "effort": {"type": "string"},
            "details": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string"}},
            "required": ["day", "type", "title", "minutes", "effort", "details"]}}},
        "required": ["week", "sessions"]}}}, "required": ["weeks"]},
}


def _loads_lenient(text: str):
    """json.loads, tolerating code fences, text around the object and trailing commas."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise ValueError("no JSON object found")
    s = m.group(0)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        try:
            return json.loads(re.sub(r",\s*([}\]])", r"\1", s))
        except json.JSONDecodeError as e:
            raise ValueError(f"invalid JSON: {e}")


def parse_block(text: str, rows: list[dict]) -> list[dict]:
    data = _loads_lenient(text)
    weeks = data.get("weeks")
    if not isinstance(weeks, list):
        raise ValueError("missing 'weeks' list")
    for wk in weeks:
        wk["week"] = int(wk.get("week", 0))
        if not isinstance(wk.get("sessions"), list) or not wk["sessions"]:
            raise ValueError(f"week {wk['week']} has no sessions")
    have = {w["week"] for w in weeks}
    need = {r["week"] for r in rows}
    if not need <= have:
        raise ValueError(f"missing weeks {sorted(need - have)}")
    return [w for w in weeks if w["week"] in need]


def _minutes(s) -> int:
    try:
        return int(float(s.get("minutes", 0) or 0))
    except (TypeError, ValueError):
        return 0


def lint_week(wk: dict, row: dict, p) -> list[tuple[str, str]]:
    out, w = [], row["week"]
    ss = [s for s in wk.get("sessions", []) if s.get("type") in COUNTED]
    if len(ss) != p.days_per_week:
        out.append(("error", f"Week {w}: {len(ss)} training sessions, expected exactly {p.days_per_week}."))
    days = [s.get("day") for s in ss]
    if len(set(days)) != len(days) or any(d not in VALID_DAYS for d in days):
        out.append(("error", f"Week {w}: session days must be unique and one of {', '.join(VALID_DAYS)}."))
    total = sum(_minutes(s) for s in ss)
    tgt = row["minutes"]
    if tgt and abs(total - tgt) / tgt > 0.10:
        out.append(("error", f"Week {w}: sessions total {total} min but the target is {tgt} min (allowed +/-10%)."))
    if total:
        longest = max(_minutes(s) for s in ss)
        d = p.days_per_week
        if d >= 4:
            lim = 0.40 if is_endurance(p.goal) else 0.50
        elif d == 3:
            lim = 0.45 if is_endurance(p.goal) else 0.55
        else:
            lim = 0.60
        if longest / total > lim:
            out.append(("error", f"Week {w}: longest session is {longest / total:.0%} of the week; keep it at or under {lim:.0%}."))
    quality = sum(1 for s in ss if s.get("type") == "quality")
    maxq = 1 if (p.age < 18 or p.experience.strip().lower() == "beginner") else 2
    if quality > maxq:
        out.append(("error", f"Week {w}: {quality} quality (hard) sessions, maximum is {maxq}."))
    if row.get("no_quality") and quality > 0:
        out.append(("error", f"Week {w}: no quality (hard) sessions allowed this week; use easy sessions only."))
    if (row["deload"] or row["taper"]) and quality > 1:
        out.append(("warn", f"Week {w}: {row['phase']} week should have at most one quality session."))
    order = {d: i for i, d in enumerate(VALID_DAYS)}
    hard = sorted(order[s["day"]] for s in ss if s.get("type") in ("quality", "long") and s.get("day") in order)
    if any(b - a == 1 for a, b in zip(hard, hard[1:])):
        out.append(("warn", f"Week {w}: hard sessions on consecutive days; space them out."))
    for s in ss:
        if not s.get("details") or not s.get("effort"):
            out.append(("warn", f"Week {w} {s.get('day')}: session lacks effort cue or concrete details."))
            break
    return out


def lint_block(weeks: list[dict], rows: list[dict], p) -> list[tuple[str, str]]:
    by_week = {w["week"]: w for w in weeks}
    out = []
    for r in rows:
        if r["week"] not in by_week:
            out.append(("error", f"Week {r['week']} is missing."))
        else:
            out += lint_week(by_week[r["week"]], r, p)
    return out


def _cell(x) -> str:
    return str(x).replace("|", "/").replace("\n", " ").strip()


def render_weeks(weeks: list[dict], rows: list[dict]) -> str:
    by_row = {r["week"]: r for r in rows}
    out = []
    for wk in sorted(weeks, key=lambda x: x["week"]):
        r = by_row[wk["week"]]
        out.append(f"### Week {wk['week']} · {r['phase']} · about {r['minutes']} min")
        if wk.get("focus"):
            out.append(f"*{_cell(wk['focus'])}*\n")
        out.append("| Day | Session | Time | Effort | What to do |\n|---|---|---|---|---|")
        order = {d: i for i, d in enumerate(VALID_DAYS)}
        for s in sorted(wk["sessions"], key=lambda s: order.get(s.get("day"), 9)):
            details = s.get("details", [])
            details = "; ".join(details) if isinstance(details, list) else details
            why = f". Why: {s['why']}" if s.get("why") else ""
            out.append(f"| {_cell(s.get('day', ''))} | **{_cell(s.get('title', ''))}** ({_cell(s.get('type', ''))}) | "
                       f"{_minutes(s)} min | {_cell(s.get('effort', ''))} | {_cell(details)}{_cell(why)} |")
        if wk.get("notes"):
            out.append(f"\n{_cell(wk['notes'])}")
        out.append("")
    return "\n".join(out)


def outline_table(rows: list[dict]) -> str:
    return "| Week | Phase | Target minutes |\n|---|---|---|\n" + "\n".join(
        f"| {r['week']} | {r['phase']} | {r['minutes']} |" for r in rows)
