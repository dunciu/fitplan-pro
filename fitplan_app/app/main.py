import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import knowledge, scheduler
from .beta_api import build_app
from .llm import MODEL, get_llm
from .pipeline import followup, run_pipeline
from .schemas import AskRequest, Profile

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "static" / "app"


@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(scheduler.loop(get_llm))  # weekly auto-adaptation
    yield
    task.cancel()


app = FastAPI(title="FitPlan Pro", lifespan=lifespan)
app.mount("/api/v2", build_app())                                   # phone app API
app.mount("/app", StaticFiles(directory=APP_DIR), name="app")       # phone app assets
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(APP_DIR / "index.html")


@app.get("/connected")
def connected(provider: str = ""):
    """Landing page after an OAuth sign-in. Works whether it was opened from the phone app or the web app."""
    from fastapi.responses import HTMLResponse
    name = {"whoop": "WHOOP", "google": "Google Health"}.get(provider, "Your tracker")
    return HTMLResponse(f"""<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">
<body style="font-family:system-ui;background:#f4f2ec;color:#17201b;display:grid;place-items:center;min-height:90vh;text-align:center;padding:16px">
<div><h1>{name} connected</h1><p>Your data is syncing. You can close this page and go back to FitPlan.</p>
<p><a href="/" style="color:#176b4d">Open the web app</a></p></div></body>""")


@app.get("/classic")
def classic():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/sw.js")
def service_worker():
    return FileResponse(APP_DIR / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(APP_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/api/health")
def health():
    _, mock = get_llm()
    return {"ok": True, "mock_mode": mock, "model": None if mock else MODEL, "data": knowledge.source_info()}


@app.post("/api/plan")
async def plan(profile: Profile):
    llm, _ = get_llm()

    async def events():
        try:
            async for ev in run_pipeline(profile, llm):
                yield f"data: {json.dumps(ev)}\n\n"
        except Exception as e:  # surface a readable error instead of a dropped stream
            yield f"data: {json.dumps({'stage': 'error', 'status': 'error', 'message': str(e)[:300]})}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/api/ask")
async def ask(req: AskRequest):
    llm, _ = get_llm()
    return {"answer": await followup(req.question, req.plan, req.age, llm)}
