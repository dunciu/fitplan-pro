"""Phone-app API (Starlette sub-app, mounted at /api/v2). Anonymous per-device accounts for the beta:
the app creates a random token on first launch and sends it in X-User-Token."""
import asyncio
import datetime as dt
import json
import os
from statistics import mean

from pydantic import BaseModel, Field, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.routing import Route

from . import autopilot, coach, db, demo, sync
from .adapt import adapt_user, iso_week
from .ingest import parse_upload
from .llm import MODEL, get_llm
from .pipeline import followup, run_pipeline
from .planlint import VALID_DAYS, render_weeks
from .schemas import Profile

MAX_UPLOAD = 60 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        self.status, self.message = status, message


async def _api_error(request, exc: ApiError):
    return JSONResponse({"error": exc.message}, status_code=exc.status)


def j(data, status: int = 200):
    return JSONResponse(data, status_code=status)


def sse(ev: dict) -> str:
    return f"data: {json.dumps(ev)}\n\n"


async def body(request: Request) -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def auth(request: Request) -> dict:
    u = db.user_by_token(request.headers.get("x-user-token", ""))
    if not u:
        raise ApiError(401, "Unknown device. Reload the app.")
    return u


def day(request: Request, data: dict | None = None) -> dt.date:
    s = request.query_params.get("date") or (data or {}).get("date")
    if not s:
        return dt.date.today()
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        raise ApiError(400, "Dates must look like 2026-10-15.")


def _brief(s):
    return {"type": s["type"], "title": s.get("title", ""), "minutes": s.get("minutes")} if s else None


# --- models ------------------------------------------------------------------------------------------------
class LogIn(BaseModel):
    date: str | None = None
    sleep_h: float | None = Field(None, ge=0, le=16)
    rhr: float | None = Field(None, ge=30, le=130)
    hrv: float | None = Field(None, ge=5, le=300)
    steps: int | None = Field(None, ge=0, le=100000)
    soreness: int | None = Field(None, ge=0, le=10)
    mood: int | None = Field(None, ge=1, le=5)
    effort: int | None = Field(None, ge=1, le=10)
    done: int | None = Field(None, ge=0, le=1)
    notes: str | None = Field(None, max_length=400)


# --- handlers ----------------------------------------------------------------------------------------------
async def health(request):
    _, mock = get_llm()
    return j({"ok": True, "mock_mode": mock, "model": None if mock else MODEL})


async def create_session(request):
    u = db.new_user()
    return j({"token": u["token"]})


async def me(request):
    u = auth(request)
    plan = db.active_plan(u["id"])
    _, mock = get_llm()
    return j({
        "profile": json.loads(u["profile"]) if u["profile"] else None,
        "safety": json.loads(u["safety"]) if u["safety"] else None,
        "plan": {"version": plan["version"], "start_date": plan["start_date"], "weeks": len(plan["outline"])} if plan else None,
        "unseen": db.unseen_count(u["id"]), "data_days": db.count_logs(u["id"]), "mock_mode": mock,
        "autopilot": db.autopilot_on(u["id"]),
        "reviewing": bool(JOBS.get(u["id"]) and not JOBS[u["id"]]["done"]),
        "demo_enabled": os.getenv("FITPLAN_ALLOW_DEMO", "1") != "0"})


async def delete_me(request):
    db.delete_user(auth(request)["id"])
    return j({"ok": True})


JOBS: dict[int, dict] = {}   # plan generation runs in the background; the stream just tails it


def _slim(ev: dict) -> dict:
    return {k: v for k, v in ev.items() if k not in ("framework", "weeks", "outline", "markdown")}


async def _generate(uid: int, profile: Profile, start: dt.date, today: dt.date, job: dict):
    llm, _ = get_llm()
    try:
        async for ev in run_pipeline(profile, llm):
            if ev["stage"] == "safety":
                db.set_profile(uid, profile.model_dump(), ev["data"])
            elif ev["stage"] == "draft":
                v = db.save_plan(uid, start.isoformat(), ev["framework"], ev["weeks"], ev["outline"], "draft")
                db.set_last_adapt(uid, iso_week(today))
                ev = {"stage": "draft", "status": "ok", "version": v}
            elif ev["stage"] == "final" and ev["status"] == "ok":
                v = db.save_plan(uid, start.isoformat(), ev["framework"], ev["weeks"], ev["outline"], "reviewed")
                db.save_report(uid, v, ev["report"])
                ev = {"stage": "final", "status": "ok", "version": v, "report": ev["report"]}
            job["events"].append(_slim(ev))
    except Exception as e:
        db.log_run(uid, "onboard", "error", str(e))
        has_draft = db.active_plan(uid) is not None
        job["events"].append({"stage": "error", "status": "error", "draft_kept": has_draft,
                              "message": ("The review step failed, so you have the unreviewed plan: " if has_draft else "") + str(e)[:300]})
    finally:
        job["done"] = True


async def onboard(request):
    u = auth(request)
    data = await body(request)
    today = day(request, data)
    try:
        profile = Profile.model_validate({k: v for k, v in data.items() if k != "date"})
    except ValidationError as e:
        raise ApiError(422, "Please check your answers: " + "; ".join(f"{'.'.join(map(str, x['loc']))} {x['msg']}" for x in e.errors()[:3]))
    old = JOBS.get(u["id"])
    if old and not old["done"]:
        raise ApiError(409, "A plan is already being built. Hang on a moment.")
    job = {"events": [], "done": False, "started": db.now()}
    JOBS[u["id"]] = job
    start = today - dt.timedelta(days=today.weekday())
    job["task"] = asyncio.create_task(_generate(u["id"], profile, start, today, job))
    if request.query_params.get("nostream") == "1":   # phone app: start now, then poll /onboard/status
        return j({"started": True}, status=202)

    async def tail():
        i = 0
        while True:
            while i < len(job["events"]):
                yield sse(job["events"][i])
                i += 1
            if job["done"] and i >= len(job["events"]):
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(tail(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


async def onboard_status(request):
    job = JOBS.get(auth(request)["id"])
    if not job:
        return j({"running": False, "events": []})
    return j({"running": not job["done"], "events": job["events"][-8:], "started": job["started"]})


async def rate_plan(request):
    u = auth(request)
    data = await body(request)
    r = data.get("rating")
    if r not in (1, -1):
        raise ApiError(422, "rating must be 1 or -1")
    db.rate_report(u["id"], r, str(data.get("note", "")))
    return j({"ok": True})


async def get_plan(request):
    u = auth(request)
    plan = db.active_plan(u["id"])
    if not plan:
        raise ApiError(404, "No plan yet.")
    rep = db.latest_report(u["id"])
    job = JOBS.get(u["id"])
    return j({"version": plan["version"], "start_date": plan["start_date"], "status": plan["note"],
              "reviewing": bool(job and not job["done"]),
              "framework": plan["framework"].replace("{{WEEKLY_PLAN}}", "").strip(),
              "weeks": plan["weeks"], "outline": plan["outline"],
              "report": rep["report"] if rep else None, "rating": rep["rating"] if rep else None})


async def today_view(request):
    u = auth(request)
    plan, d = db.active_plan(u["id"]), day(request)
    if not plan:
        return j({"has_plan": False})
    start = dt.date.fromisoformat(plan["start_date"])
    idx, n = (d - start).days // 7, len(plan["outline"])
    planned = coach.planned_sessions(plan["weeks"], plan["start_date"])
    log = next(iter(db.get_logs(u["id"], d.isoformat(), d.isoformat())), None)
    acts = [a for a in db.list_actions(u["id"], date=d.isoformat()) if not a["undone"]]
    res = {"has_plan": True, "action": acts[0] if acts else None, "date": d.isoformat(), "weekday": VALID_DAYS[d.weekday()], "logged": log,
           "complete": idx >= n, "before_start": idx < 0, "session": None, "strip": []}
    if 0 <= idx < n:
        row = plan["outline"][idx]
        wk = next((w for w in plan["weeks"] if w["week"] == row["week"]), {})
        res.update(week=row["week"], phase=row["phase"], target_minutes=row["minutes"], focus=wk.get("focus"),
                   notes=wk.get("notes"), session=planned.get(d.isoformat()), adapted=bool(row.get("adapted")))
        ws = start + dt.timedelta(days=7 * idx)
        logs = {l["date"]: l for l in db.get_logs(u["id"], ws.isoformat(), (ws + dt.timedelta(days=6)).isoformat())}
        for i in range(7):
            x = (ws + dt.timedelta(days=i)).isoformat()
            res["strip"].append({"date": x, "weekday": VALID_DAYS[i], "session": _brief(planned.get(x)),
                                 "done": (logs.get(x) or {}).get("done"), "today": x == d.isoformat()})
    return j(res)


async def post_log(request):
    u = auth(request)
    data = await body(request)
    try:
        m = LogIn.model_validate(data)
    except ValidationError as e:
        raise ApiError(422, "; ".join(f"{x['loc'][0]}: {x['msg']}" for x in e.errors()[:3]))
    d = day(request, data)
    fields = m.model_dump(exclude={"date"})
    db.upsert_log(u["id"], d.isoformat(), source="manual", **fields)
    return j({"ok": True, "log": db.get_logs(u["id"], d.isoformat(), d.isoformat())[0],
              "autopilot": autopilot.check(u["id"], d)})


async def trends(request):
    u = auth(request)
    days = max(7, min(90, int(request.query_params.get("days", "28") or 28)))
    end = day(request)
    start = end - dt.timedelta(days=days - 1)
    logs = db.get_logs(u["id"], (end - dt.timedelta(days=max(days, 28) - 1)).isoformat(), end.isoformat())
    plan = db.active_plan(u["id"])
    planned = coach.planned_sessions(plan["weeks"], plan["start_date"]) if plan else {}
    mt = coach.metrics(logs, end, planned)
    decision, reasons = coach.decide(mt)
    by = {l["date"]: l for l in logs}
    series = {k: [{"date": (start + dt.timedelta(days=i)).isoformat(),
                   "v": by.get((start + dt.timedelta(days=i)).isoformat(), {}).get(k)} for i in range(days)]
              for k in ("hrv", "rhr", "sleep_h")}
    sleeps = [l["sleep_h"] for l in logs if l.get("sleep_h") is not None]
    return j({"series": series, "baseline": {"hrv": mt["hrv_base"], "rhr": mt["rhr_base"], "sleep_h": mean(sleeps) if sleeps else None},
              "metrics": coach.fmt_metrics(mt), "decision": decision, "label": coach.LABELS[decision],
              "readiness": coach.READINESS[decision], "reasons": reasons, "data_days": len(logs)})


async def upload(request):
    u = auth(request)
    if int(request.headers.get("content-length", "0") or 0) > MAX_UPLOAD:
        raise ApiError(413, "File too large (max 60 MB). For Apple Health, export again and upload the zip.")
    data = await request.body()
    if len(data) > MAX_UPLOAD:
        raise ApiError(413, "File too large (max 60 MB).")
    try:
        res = await asyncio.to_thread(parse_upload, data, request.query_params.get("filename", ""))
    except ValueError as e:
        raise ApiError(422, str(e))
    except Exception:
        raise ApiError(422, "Couldn't read that file. Use a CSV export or the Apple Health export zip.")
    for d, row in res["days"].items():
        db.upsert_log(u["id"], d, source=res["kind"], **row)
    ds = sorted(res["days"])
    return j({"imported_days": len(ds), "dropped_values": res["dropped"], "from": ds[0] if ds else None, "to": ds[-1] if ds else None,
              "autopilot": autopilot.check(u["id"], day(request))})


async def adapt(request):
    u = auth(request)
    data = await body(request)
    llm, _ = get_llm()
    try:
        res = await adapt_user(u["id"], llm, day(request, data))
    except ApiError:
        raise
    except Exception as e:
        db.log_run(u["id"], "adapt", "error", str(e))
        raise ApiError(500, "Adapting failed: " + str(e)[:200])
    if not res.get("ok"):
        raise ApiError(400, res.get("error", "Couldn't adapt."))
    return j(res)


async def checkins(request):
    u = auth(request)
    items = db.list_checkins(u["id"])
    return j({"items": items})


async def checkins_seen(request):
    db.mark_seen(auth(request)["id"])
    return j({"ok": True})


async def demo_seed(request):
    if os.getenv("FITPLAN_ALLOW_DEMO", "1") == "0":
        raise ApiError(403, "Demo data is disabled.")
    u = auth(request)
    data = await body(request)
    scenario = data.get("scenario", "steady")
    if scenario not in demo.SCENARIOS:
        raise ApiError(400, "Unknown scenario.")
    d = day(request, data)
    plan = db.active_plan(u["id"])
    planned = coach.planned_sessions(plan["weeks"], plan["start_date"]) if plan else {}
    rows = demo.seed(scenario, d, planned)
    for k, row in rows.items():
        db.upsert_log(u["id"], k, **row)
    return j({"ok": True, "days": len(rows), "scenario": scenario})


async def ask(request):
    u = auth(request)
    data = await body(request)
    q = str(data.get("question", "")).strip()
    if len(q) < 2 or len(q) > 1000:
        raise ApiError(422, "Ask a question between 2 and 1000 characters.")
    plan = db.active_plan(u["id"])
    if not plan or not u["profile"]:
        raise ApiError(400, "Create a plan first.")
    profile = json.loads(u["profile"])
    text = plan["framework"].replace("{{WEEKLY_PLAN}}", render_weeks(plan["weeks"], plan["outline"]))[:14000]
    llm, _ = get_llm()
    try:
        answer = await followup(q, text, int(profile["age"]), llm)
    except Exception as e:
        raise ApiError(500, "Couldn't answer: " + str(e)[:200])
    return j({"answer": answer})


async def autopilot_run(request):
    u = auth(request)
    data = await body(request)
    llm, _ = get_llm()
    try:
        res = await autopilot.run(u["id"], day(request, data), llm)
    except Exception as e:
        db.log_run(u["id"], "autopilot", "error", str(e))
        raise ApiError(500, "The coach couldn't adjust your plan: " + str(e)[:200])
    return j(res)


async def actions(request):
    return j({"items": db.list_actions(auth(request)["id"])})


async def action_undo(request):
    u = auth(request)
    data = await body(request)
    try:
        aid = int(data.get("id"))
    except (TypeError, ValueError):
        raise ApiError(400, "Missing action id.")
    res = autopilot.undo(u["id"], aid)
    if not res["ok"]:
        raise ApiError(400, res["error"])
    return j(res)


async def settings(request):
    u = auth(request)
    data = await body(request)
    if "autopilot" in data:
        db.set_autopilot(u["id"], bool(data["autopilot"]))
    return j({"autopilot": db.autopilot_on(u["id"])})


# --- live sync ------------------------------------------------------------------------------------------------
def _autopilot_soon(uid: int, d: dt.date):
    """After new data arrives, let the autopilot look at today without blocking the sender."""
    chk = autopilot.check(uid, d)
    if chk["triggered"] or chk.get("screen_note"):
        async def go():
            try:
                llm, _ = get_llm()
                await autopilot.run(uid, d, llm)
            except Exception as e:
                db.log_run(uid, "autopilot_sync", "error", str(e))
        asyncio.get_running_loop().create_task(go())
    return chk


async def sync_info(request):
    u = auth(request)
    base = str(request.base_url).rstrip("/")
    conns = {}
    for key, p in sync.PROVIDERS.items():
        c = sync.get_conn(u["id"], key) or {}
        conns[key] = {"name": p["name"], "configured": p["configured"](), "connected": c.get("status") == "connected",
                      "last_sync": c.get("last_sync")}
    return j({"push_url": f"{base}/api/v2/sync/push", "push_key": sync.sync_key(u["id"]), "last_push": sync.last_push(u["id"]),
              "sync_minutes": sync.sync_minutes(), "connections": conns, "whoop": conns["whoop"], "google": conns["google"]})


async def sync_rotate(request):
    return j({"push_key": sync.sync_key(auth(request)["id"], rotate=True)})


async def sync_push(request):
    key = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("key", "")
    uid = sync.user_for_key(key)
    if not uid:
        raise ApiError(401, "Unknown sync key. Copy it again from the app (Settings → Live sync).")
    if int(request.headers.get("content-length", "0") or 0) > 10 * 1024 * 1024:
        raise ApiError(413, "Payload too large (max 10 MB). Send fewer days at a time.")
    data = await body(request)
    try:
        res = sync.parse_push(data)
    except ValueError as e:
        raise ApiError(422, str(e))
    dates = sync.store(uid, res["days"], "push")
    return j({"imported_days": len(dates), "dropped_values": res["dropped"], "dates": dates[-7:],
              "autopilot": _autopilot_soon(uid, dt.date.today())})


def _provider(request):
    key = request.path_params["provider"]
    if key not in sync.PROVIDERS:
        raise ApiError(404, "Unknown provider.")
    return key, sync.PROVIDERS[key]


ENV_HINT = {"whoop": "WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET and WHOOP_REDIRECT_URI",
            "google": "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI"}


async def connect_start(request):
    u = auth(request)
    key, p = _provider(request)
    if not p["configured"]():
        raise ApiError(400, f"{p['name']} isn't set up on this server. Set {ENV_HINT[key]}.")
    return j({"url": p["auth_url"](u["id"])})


async def connect_callback(request):
    key, p = _provider(request)
    q = request.query_params
    if q.get("error"):
        return RedirectResponse(f"/?connect_error={q.get('error')}", status_code=303)
    try:
        uid = await p["callback"](q.get("code", ""), q.get("state", ""))
        await p["sync"](uid, days=28)
        _autopilot_soon(uid, dt.date.today())
    except Exception as e:
        return RedirectResponse("/?connect_error=" + str(e)[:80].replace(" ", "+"), status_code=303)
    return RedirectResponse(f"/connected?provider={key}", status_code=303)


async def connect_sync(request):
    u = auth(request)
    key, p = _provider(request)
    try:
        dates = await p["sync"](u["id"])
    except Exception as e:
        raise ApiError(400, f"{p['name']} sync failed: " + str(e)[:200])
    return j({"imported_days": len(dates), "autopilot": _autopilot_soon(u["id"], dt.date.today())})


async def connect_disconnect(request):
    key, _ = _provider(request)
    sync.delete_conn(auth(request)["id"], key)
    return j({"ok": True})


async def pair_create(request):
    return j({"code": sync.pair_create(auth(request)["id"]), "expires_in": 600})


async def pair_claim(request):
    data = await body(request)
    tok = sync.pair_claim(str(data.get("code", "")))
    if not tok:
        raise ApiError(400, "That code is wrong or has expired. Make a new one in Settings on your other device.")
    return j({"token": tok})


def build_app() -> Starlette:
    db.init()
    sync.init()
    routes = [
        Route("/health", health), Route("/session", create_session, methods=["POST"]),
        Route("/me", me), Route("/me", delete_me, methods=["DELETE"]),
        Route("/onboard", onboard, methods=["POST"]), Route("/onboard/status", onboard_status),
        Route("/plan/rate", rate_plan, methods=["POST"]), Route("/plan", get_plan), Route("/today", today_view),
        Route("/log", post_log, methods=["POST"]), Route("/trends", trends),
        Route("/upload", upload, methods=["POST"]), Route("/adapt", adapt, methods=["POST"]),
        Route("/checkins", checkins), Route("/checkins/seen", checkins_seen, methods=["POST"]),
        Route("/demo/seed", demo_seed, methods=["POST"]), Route("/ask", ask, methods=["POST"]),
        Route("/autopilot", autopilot_run, methods=["POST"]), Route("/actions", actions),
        Route("/actions/undo", action_undo, methods=["POST"]), Route("/settings", settings, methods=["POST"]),
        Route("/sync/info", sync_info), Route("/sync/rotate", sync_rotate, methods=["POST"]),
        Route("/sync/push", sync_push, methods=["POST"]),
        Route("/connect/{provider}/start", connect_start, methods=["POST"]), Route("/connect/{provider}/callback", connect_callback),
        Route("/connect/{provider}/sync", connect_sync, methods=["POST"]),
        Route("/connect/{provider}/disconnect", connect_disconnect, methods=["POST"]),
        Route("/pair/create", pair_create, methods=["POST"]), Route("/pair/claim", pair_claim, methods=["POST"]),
    ]
    return Starlette(routes=routes, exception_handlers={ApiError: _api_error})
