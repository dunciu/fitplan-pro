"""Background loop: once per week (default Sunday 18:00 server time) adapt every user's next week.
Runs inside the web process for the beta. For production move it to a worker/cron so it survives restarts.
Env: FITPLAN_AUTO_ADAPT=0 disables; FITPLAN_ADAPT_WEEKDAY (0=Mon..6=Sun, default 6); FITPLAN_ADAPT_HOUR (default 18)."""
import asyncio
import datetime as dt
import os

from . import db
from . import autopilot
from .adapt import adapt_user, iso_week

_last_daily = {"date": None}


async def run_daily(get_llm_fn, now: dt.datetime | None = None) -> int:
    """Morning autopilot pass (default 07:00 server time; FITPLAN_DAILY_HOUR, FITPLAN_AUTOPILOT=0 disables).
    Each user's run is idempotent per day, so a restart that repeats the pass is harmless."""
    if os.getenv("FITPLAN_AUTOPILOT", "1") == "0":
        return 0
    now = now or dt.datetime.now()
    if now.hour < int(os.getenv("FITPLAN_DAILY_HOUR", "7")) or _last_daily["date"] == now.date():
        return 0
    _last_daily["date"] = now.date()
    return await autopilot.daily_pass(get_llm_fn, now.date())


async def run_sync(get_llm_fn, now: dt.datetime | None = None) -> int:
    """Pull every connected provider (WHOOP, Google Health) every FITPLAN_SYNC_MINUTES (default 60, min 15),
    then let the autopilot look at today. A failing account backs off for one interval."""
    from . import sync
    now, n = now or dt.datetime.now(), 0
    for key, p in sync.PROVIDERS.items():
        for uid in sync.connected(key):
            c = sync.get_conn(uid, key)
            last = dt.datetime.fromisoformat(c["last_sync"]) if c.get("last_sync") else None
            if last and (now - last).total_seconds() < sync.sync_minutes() * 60 - 60:
                continue
            try:
                await p["sync"](uid)
                if autopilot.check(uid, now.date())["triggered"]:
                    llm, _ = get_llm_fn()
                    await autopilot.run(uid, now.date(), llm)
                n += 1
            except Exception as e:
                db.log_run(uid, f"{key}_sync", "error", str(e))
                sync.save_conn(uid, key, last_sync=now.isoformat(timespec="seconds"))
    return n


async def run_due(get_llm_fn, now: dt.datetime | None = None) -> int:
    if os.getenv("FITPLAN_AUTO_ADAPT", "1") == "0":
        return 0
    now = now or dt.datetime.now()
    if now.weekday() != int(os.getenv("FITPLAN_ADAPT_WEEKDAY", "6")) or now.hour < int(os.getenv("FITPLAN_ADAPT_HOUR", "18")):
        return 0
    key, done = iso_week(now.date()), 0
    for u in db.users_with_plans():
        if u["last_adapt_week"] == key:
            continue
        llm, _ = get_llm_fn()
        try:
            res = await adapt_user(u["id"], llm, now.date())
            db.log_run(u["id"], "scheduled_adapt", "ok" if res.get("ok") else "skipped", res.get("decision") or res.get("error", ""))
        except Exception as e:  # never loop on a failing user: mark the week as attempted
            db.log_run(u["id"], "scheduled_adapt", "error", str(e))
            db.set_last_adapt(u["id"], key)
        done += 1
    return done


async def loop(get_llm_fn, interval: int = 900):
    while True:
        for job in (run_sync, run_daily, run_due):
            try:
                await job(get_llm_fn)
            except Exception:
                pass
        await asyncio.sleep(interval)
