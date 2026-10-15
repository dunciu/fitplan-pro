"""Proof-of-run trace: one person, start to finish, with every agent step timestamped.

  python -m tools.trace            # mock model (free, no key): shows the orchestration
  python -m tools.trace --real     # real Claude (needs ANTHROPIC_API_KEY, costs a few cents)

Steps: safety screen -> research + session builders in parallel -> draft -> critic -> targeted rebuilds/editor
-> final report; then a sore morning -> autopilot tool loop with guardrails -> undo; then a red-flag note ->
escalation; then 4 weeks of overreaching data -> weekly coach review. Writes evals/trace_<timestamp>.log."""
import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import tempfile
import time

ap = argparse.ArgumentParser()
ap.add_argument("--real", action="store_true")
ap.add_argument("--goal", default="run a half marathon")
ap.add_argument("--weeks", type=int, default=12)
args = ap.parse_args()
if not args.real:
    os.environ["FITPLAN_MOCK"] = "1"
os.environ.setdefault("FITPLAN_DB", os.path.join(tempfile.mkdtemp(), "trace.db"))

from app import autopilot, coach, db, demo  # noqa: E402
from app.adapt import adapt_user  # noqa: E402
from app.llm import AnthropicLLM, MockLLM  # noqa: E402
from app.pipeline import run_pipeline  # noqa: E402
from app.schemas import Profile  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
STAMP = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = os.path.join(ROOT, "evals", f"trace_{STAMP}.log")
T0 = time.monotonic()
lines: list[str] = []


def log(agent: str, msg: str):
    line = f"[{time.monotonic() - T0:7.1f}s] {agent:<11} {msg}"
    print(line, flush=True)
    lines.append(line)


def short(x, n=160):
    s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
    s = " ".join(s.split())
    return s if len(s) <= n else s[:n - 1] + "…"


async def main():
    db.init()
    llm = AnthropicLLM() if args.real else MockLLM()
    log("run", f"mode={'REAL Claude (' + os.getenv('FITPLAN_MODEL', 'claude-sonnet-5-5') + ')' if args.real else 'MOCK model (no API calls)'}")
    profile = Profile(goal=args.goal, age=34, experience="intermediate", weeks=args.weeks, days_per_week=4,
                      injuries="old ankle sprain", equipment="none")
    log("user", f"onboard: {short(profile.model_dump(exclude_none=True))}")

    # 1. Plan pipeline -----------------------------------------------------------------
    final = None
    async for ev in run_pipeline(profile, llm):
        st, status = ev["stage"], ev.get("status")
        if st == "safety":
            d = ev["data"]
            log("safety", f"level={d.get('level')} flags={d.get('flags')} constraints={len(d.get('constraints', []))}")
        elif st == "research" and status == "running":
            log("research", ev.get("message", ""))
        elif st == "research":
            d = ev["data"]
            log("research", f"guide written; {d['weeks']} weeks built; linter errors={d['automated_errors']} warnings={d['automated_warnings']}")
        elif st == "draft":
            log("draft", f"usable plan saved early ({len(ev['weeks'])} weeks) - the app opens it now")
        elif st == "critic" and status == "done":
            c = ev["data"]
            log("critic", f"verdict={c.get('verdict')} issues={len(c.get('issues', []))}")
            for i in c.get("issues", [])[:6]:
                log("critic", f"  [{i.get('severity')}] {i.get('where')}: {short(i.get('problem', ''), 110)}")
        elif st == "editor" and status == "running":
            log("editor", ev.get("message", ""))
        elif st == "final":
            final = ev
            if status == "hold":
                log("final", "HELD for safety: " + short(ev["markdown"]))
                return
            r = ev["report"]
            log("final", f"timings={r['timings_s']} calls={r['model_calls']} tokens={r['tokens']}")
            log("final", f"checks={r['checks']} rebuilt_blocks={r['rebuilt_blocks']} editor_rewrite={r['editor_rewrite']}")
            for c in r["changes"]:
                log("final", "  change: " + short(c, 140))

    u = db.new_user()
    uid = u["id"]
    db.set_profile(uid, profile.model_dump(), {"level": "ok"})
    today = dt.date.today()
    start = today - dt.timedelta(days=today.weekday() + 7)      # plan started last Monday-week, so there is history
    db.save_plan(uid, start.isoformat(), final["framework"], final["weeks"], final["outline"], "initial")
    log("db", f"plan v{db.active_plan(uid)['version']} saved for user {uid}")

    # 2. Autopilot on a sore morning --------------------------------------------------------
    db.upsert_log(uid, today.isoformat(), soreness=8, sleep_h=5.4)
    log("user", "check-in: soreness 8/10, slept 5.4 h")
    res = await autopilot.run(uid, today, llm)
    a = res.get("action") or {}
    log("autopilot", f"triggers={a.get('triggers')} kind={a.get('kind')}")
    for s in a.get("steps", []):
        log("autopilot", f"  tool {s.get('tool')}({short(s.get('input'), 90)}) -> {short(s.get('result'), 90)}")
    log("autopilot", "message: " + short(a.get("message", "")))
    log("db", f"plan now v{db.active_plan(uid)['version']}")
    again = await autopilot.run(uid, today, llm)
    log("autopilot", f"second run same day: acted={again['acted']} ({again.get('reason')}) - idempotent")
    if a.get("id"):
        u2 = autopilot.undo(uid, a["id"])
        log("user", f"tapped Undo -> ok={u2.get('ok')}, previous plan restored (saved as v{db.active_plan(uid)['version']}, history kept)")

    # 3. Red flag in a note ---------------------------------------------------------------
    tomorrow = today + dt.timedelta(days=1)
    db.upsert_log(uid, tomorrow.isoformat(), notes="felt a pressure in my chest on the hill")
    log("user", "note: 'felt a pressure in my chest on the hill'")
    res = await autopilot.run(uid, tomorrow, llm)
    a = res.get("action") or {}
    log("safety", f"autopilot kind={a.get('kind')} flags={a.get('triggers')} -> {short(a.get('message', ''), 120)}")

    # 4. Weekly review on 4 weeks of overreaching data ---------------------------------------
    plan = db.active_plan(uid)
    planned = coach.planned_sessions(plan["weeks"], plan["start_date"])
    for k, row in demo.seed("overreaching", today, planned).items():
        db.upsert_log(uid, k, **row)
    log("data", "28 days of synced data (overreaching pattern: HRV falling, resting HR rising)")
    r = await adapt_user(uid, llm, today)
    log("coach", f"weekly decision={r.get('decision')} plan_changed={r.get('plan_changed')}")
    for why in r.get("reasons", [])[:4]:
        log("coach", "  because " + short(why, 130))
    log("run", f"done in {time.monotonic() - T0:.1f}s")


try:
    asyncio.run(main())
finally:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\nTrace written to {OUT}", file=sys.stderr)
