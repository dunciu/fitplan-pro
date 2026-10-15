"""Deterministic coaching rules: turn a person's recent logs into a weekly decision. No model involved.
Mirrors the rules used to label the training data, adapted to the signals the app stores (sleep, resting HR, HRV,
soreness, whether planned sessions were done)."""
import datetime as dt
from statistics import mean

from .planlint import COUNTED, VALID_DAYS


def planned_sessions(weeks: list[dict], start_date: str) -> dict[str, dict]:
    start, out = dt.date.fromisoformat(start_date), {}
    for wk in weeks:
        for s in wk["sessions"]:
            if s.get("type") in COUNTED and s.get("day") in VALID_DAYS:
                d = start + dt.timedelta(days=7 * (wk["week"] - 1) + VALID_DAYS.index(s["day"]))
                out[d.isoformat()] = s
    return out


def metrics(logs: list[dict], end: dt.date, planned: dict[str, dict]) -> dict:
    by = {l["date"]: l for l in logs}
    last = [(end - dt.timedelta(days=i)).isoformat() for i in range(7)]          # newest first
    base = [(end - dt.timedelta(days=i)).isoformat() for i in range(7, 28)]

    def vals(days, k):
        return [by[d][k] for d in days if d in by and by[d].get(k) is not None]

    m = lambda v: mean(v) if v else None
    hb, hl, rb, rl, r3 = vals(base, "hrv"), vals(last, "hrv"), vals(base, "rhr"), vals(last, "rhr"), vals(last[:3], "rhr")
    h3 = vals(last[:3], "hrv")
    sl, so = vals(last, "sleep_h"), vals(last, "soreness")
    plan_days = [d for d in last if d in planned]
    done = sum(1 for d in plan_days if by.get(d, {}).get("done") == 1)
    return dict(
        hrv_base=m(hb), hrv_last=m(hl), hrv_pct=(m(hl) / m(hb) - 1) if len(hb) >= 5 and hl else None,
        rhr_base=m(rb), rhr_last=m(rl), rhr_d=(m(rl) - m(rb)) if len(rb) >= 5 and rl else None,
        rhr3_d=(m(r3) - m(rb)) if len(rb) >= 5 and r3 else None,
        hrv3_pct=(m(h3) / m(hb) - 1) if len(hb) >= 5 and h3 else None,
        sleep=m(sl) if len(sl) >= 3 else None, soreness=m(so),
        logged=sum(1 for d in last if d in by), planned=len(plan_days), done=done,
        adherence=(done / len(plan_days)) if plan_days else None)


def decide(mt: dict) -> tuple[str, list[str]]:
    hp, rd, r3, sl, so, ad = (mt[k] for k in ("hrv_pct", "rhr_d", "rhr3_d", "sleep", "soreness", "adherence"))
    h3 = mt.get("hrv3_pct")
    if r3 is not None and r3 >= 8 and h3 is not None and h3 <= -0.25:
        return "rest_illness", [f"Over the last 3 days your resting heart rate is {r3:+.0f} bpm above baseline and HRV is "
                                f"{h3:+.0%} vs baseline. This pattern often goes with illness."]
    deload = []
    if hp is not None and hp <= -0.15:
        deload.append(f"HRV is {hp:+.0%} vs your own baseline")
    if rd is not None and rd >= 4 and sl is not None and sl < 6.5:
        deload.append(f"resting heart rate is up {rd:.0f} bpm and sleep averages {sl:.1f} h")
    if so is not None and so >= 8:
        deload.append(f"soreness averages {so:.0f}/10")
    if deload:
        return "deload", deload
    easy = []
    if sl is not None and sl < 6.3:
        easy.append(f"sleep averages {sl:.1f} h")
    if so is not None and so >= 7:
        easy.append(f"soreness averages {so:.0f}/10")
    if rd is not None and rd >= 4:
        easy.append(f"resting heart rate is up {rd:.0f} bpm")
    if easy:
        return "reduce_intensity", easy
    if mt["logged"] < 4:
        return "maintain", [f"only {mt['logged']} day(s) logged this week, so the plan is held as is. Log a few more days and I can adapt properly."]
    if ad is not None and ad < 0.5:
        return "maintain", [f"you completed {mt['done']} of {mt['planned']} planned sessions, so the load is held and the week should be easier to finish"]
    if (sl is None or sl >= 7) and (so is None or so <= 5) and (ad is None or ad >= 0.75):
        return "progress", ["recovery signals are steady" + (f" and you completed {mt['done']} of {mt['planned']} sessions" if mt["planned"] else "")]
    return "maintain", ["signals are mixed, so the load is held"]


READINESS = {"progress": "green", "maintain": "green", "reduce_intensity": "yellow", "deload": "red", "rest_illness": "red",
             "pause_and_refer": "red"}
LABELS = {"progress": "Progress", "maintain": "Hold steady", "reduce_intensity": "Ease the intensity", "deload": "Deload week",
          "rest_illness": "Rest and recover", "pause_and_refer": "Pause and see a professional"}


def fmt_metrics(mt: dict) -> list[str]:
    out = []
    if mt["hrv_pct"] is not None:
        out.append(f"HRV {mt['hrv_last']:.0f} ms vs baseline {mt['hrv_base']:.0f} ({mt['hrv_pct']:+.0%})")
    if mt["rhr_d"] is not None:
        out.append(f"Resting heart rate {mt['rhr_last']:.0f} bpm ({mt['rhr_d']:+.1f} vs baseline)")
    if mt["sleep"] is not None:
        out.append(f"Sleep {mt['sleep']:.1f} h/night")
    if mt["soreness"] is not None:
        out.append(f"Soreness {mt['soreness']:.1f}/10")
    if mt["planned"]:
        out.append(f"Sessions done {mt['done']}/{mt['planned']}")
    out.append(f"Days logged {mt['logged']}/7")
    return out
