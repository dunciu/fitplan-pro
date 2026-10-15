# FitPlan Pro

A small web app that helps people who struggle to start a fitness plan. They describe a goal (running, swimming, a sport, general fitness) and three agents produce one customised plan.

```
person -> [Safety: keywords + Claude classifier] -> Research guide  ┐ (in parallel) -> DRAFT (usable now)
                                                   Session blocks  ┘
          -> Critic -> only flagged weeks rebuilt + editor only if the guide was flagged -> REVIEWED plan + quality report
```

- **Safety screen** (`app/safety.py`): two layers. Broad keyword patterns run first in plain code; then a Claude classifier reads anything the person wrote. Either layer can stop the plan. Under 13 or any red flag (chest pain or tightness, fainting or dizziness, heart symptoms, pregnancy, disordered eating, extreme calorie targets, drug requests, possible stress fracture) means no plan, just a pointer to a professional; crisis language points to crisis support. Under 18 gets hard constraints (no calorie deficits or weight-loss advice, medical check, no marathon under 16).
- **Speed**: the research guide and all session blocks are generated at the same time; a usable draft is saved before review; the editor only rewrites the guide when the critic flagged the guide; generation runs as a background job, so closing the app doesn't stop it.
- **Research agent**: summarises evidence for the goal and writes the guide; its session builder writes the weeks.
- **Critic agent**: checks safety, internal consistency (training days match, taper maths, long-run share, deloads) and the rubric, and returns structured JSON issues.
- **Editor agent**: recompiles brief + draft + issues into the final plan and lists what it changed.
- **How the detail is built**: code (`app/planlint.py`) fixes the weekly minutes, deload weeks and taper; the research agent writes the sessions in 4-week blocks in parallel (exercises, sets x reps, effort cues, warm-ups); every block is machine-checked (sessions per week, minutes within 10% of target, long-session share, hard sessions per week) and retried once; the critic can send individual weeks back for a rebuild; `app/targets.py` supplies fixed, conservative nutrition/recovery numbers (none for under-18s). A 12-week plan costs about 7 model calls.
- **Knowledge** (`app/knowledge.py`): reads `train.jsonl` and `RUBRIC.md` from GitHub, falling back to `./data`.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env   # then export the variables, or set them in your shell
export ANTHROPIC_API_KEY=sk-ant-...
export FITPLAN_DATA_REPO=<owner>/<repo>@main:<folder-with-train.jsonl>
uvicorn app.main:app --reload
# open http://localhost:8000
```

No API key? It starts in **mock mode** with a demo plan so you can try the UI. `GET /api/health` shows the mode and whether data came from `github` or `local`.

## Measuring it

| What | How | Needs a key |
|---|---|---|
| Safety screen accuracy (incl. an unseen real-phrasing set), coach decisions, autopilot triggers, guardrail fuzzing, parser robustness, simulated latency | `python -m tools.evals` (writes `evals/results.md`) | no |
| Real plans: time to first plan and to reviewed plan, tokens, checks failed then repaired, critic issues, editor rewrites; two-layer safety on the held-out sets | `python -m tools.bench --plans 10 --safety` (writes CSVs; add your own ok/not-ok in `human_ok`) | yes |
| Your app's real usage: plan ratings, autopilot undo rate, escalations, weekly decisions, check-ins, errors | `python -m tools.report` | no |

Every plan also carries a quality report (timings, checks, critic issues, fixes) shown on the Plan screen with a thumbs up/down.

## Live sync

- **Apple Watch / Apple Health**: install *Health Auto Export* on the iPhone → Automations → REST API. URL and `Authorization: Bearer <key>` header are in the app under Settings → Live sync. Choose heart rate variability, resting heart rate, step count and sleep analysis, aggregated by day.
- **Any other source**: `POST /api/v2/sync/push` with the same header and `{"days": [{"date": "2026-10-15", "hrv": 62, "rhr": 54, "sleep_h": 7.2, "steps": 9000}]}`.
- **Fitbit Air / Pixel Watch (Google Health API)**: create a Google Cloud project, enable the Google Health API, add a Web OAuth client with redirect `http://localhost:8000/api/v2/connect/google/callback`, set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`, then Settings → Connect Google Health. Pulls daily resting heart rate, daily HRV and sleep every `FITPLAN_SYNC_MINUTES` (default 60). The legacy Fitbit Web API loses support on 30 Sep 2026 and is turned off on 30 Oct 2026, so it isn't used. Built from Google's docs; not yet tested with a live account. Full steps in `fitplan_mobile/README.md`.
- **iPhone app**: `fitplan_mobile/` (Expo Go). Link it to this account with Settings → Your iPhone → Show a pairing code.
- **WHOOP**: create an app in the WHOOP developer dashboard with redirect URL `https://<your-host>/api/v2/connect/whoop/callback`, then set `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_REDIRECT_URI`. People tap Connect WHOOP in Settings; the server pulls recovery, HRV, resting HR and sleep every hour. Written against WHOOP's v2 docs, not yet tested with a live account. Until WHOOP approves your app, only 10 members can connect.
- Every sync lets the autopilot look at today, so a bad night can ease today's session before the person opens the app.
- OAuth tokens are stored unencrypted in SQLite in this beta. Encrypt them (and use HTTPS) before real users connect.


## Phone app (beta)

The app at `/` is an installable phone web app (PWA): **Today** (session, 30-second check-in), **Plan** (week by week), **Trends** (HRV, resting HR, sleep vs your own baseline), **Coach** (weekly adaptation, ask questions), **More** (import data, demo data, delete everything). It stores data in a local SQLite file (`fitplan.db`), one anonymous account per device.

- **Weekly coach**: the rules in `app/coach.py` read the last 7 days against your own baseline and decide progress / hold / ease intensity / deload / rest. The session builder then rewrites only next week, machine-checked, and saves a new plan version. It runs automatically Sunday 18:00 server time (`FITPLAN_ADAPT_WEEKDAY`, `FITPLAN_ADAPT_HOUR`, `FITPLAN_AUTO_ADAPT=0` to disable) or on demand from the Coach tab. Notes mentioning red flags pause the plan instead.
- **Import**: Whoop / Oura / Fitbit-style CSV exports and the Apple Health export (.zip). Columns are detected by keyword and implausible values are skipped.
- **Demo data**: More -> Try demo data fills 4 weeks of sample history so you can watch the coach react without a wearable.

## Autopilot (autonomous daily agent)

When a check-in, a data import or the 07:00 morning pass shows a tough day (soreness 7+/10, under 6 h sleep, resting HR 5+ bpm above your baseline, HRV 15%+ below it, or low mood), the autopilot acts without being asked:

1. **Code decides whether to act** (`app/autopilot.py: triggers`) and runs the safety screen first. A red flag in today's note pauses training and refers the person to a professional; no model is involved.
2. **Claude decides how**, in a tool-use loop with `ease_session`, `move_session`, `rest_day` and `finish`.
3. **Code guards every tool call**: training can only get easier (lower minutes, gentler type), only today to +2 days can change, moves go later in the same week and never put two hard days back to back, max 3 changes. Rejected calls go back to Claude with the reason so it can try again.
4. **Every change is a new plan version**, logged with the trigger, each tool call and its result, and the message to the person. One tap undoes it. It runs once per day per trigger set, and the person can turn it off in Coach.

Env: `FITPLAN_AUTOPILOT=0` disables the morning pass, `FITPLAN_DAILY_HOUR` (default 7).

### Open it on your phone
1. Same Wi-Fi: start the server with `python -m uvicorn app.main:app --host 0.0.0.0 --port 8000`, find your computer's IP (`ipconfig` on Windows), open `http://<that-ip>:8000` on the phone. Allow Python through the Windows firewall if asked.
2. Plain `http://` works for trying it, but "install as an app" and offline mode need HTTPS. Use a tunnel such as Cloudflare Tunnel or ngrok, or deploy to a host with HTTPS (Render, Fly.io, Railway).
3. Then: iPhone Safari -> Share -> Add to Home Screen. Android Chrome -> menu -> Install app.

### Tests
```bash
python run_tests.py tests.test_app tests.test_beta tests.test_autopilot   # offline unit tests
python tests/smoke_http.py                            # starts the API and checks every endpoint (mock LLM)
python tests/e2e_browser.py                           # drives the phone UI in headless Chromium, saves screenshots
                                                      # (needs: pip install playwright && playwright install chromium)
```

### Beta limits
Anonymous device accounts (no passwords, no sync between devices), SQLite, scheduler runs inside the web process, no push notifications, no live Whoop/Oura/Apple connection yet (import only). Health data: add accounts, consent, encryption and a privacy policy before inviting other people.

## Test

```bash
pytest                         # full suite (needs fastapi, httpx)
python run_tests.py            # offline tests only, no pytest needed
```

## Layout

```
app/safety.py      deterministic screening and constraints
app/knowledge.py   GitHub/local example + rubric loader
app/prompts.py     the three agent prompts (+ follow-up)
app/pipeline.py    orchestration, streamed as events
app/llm.py         Anthropic wrapper + mock
app/main.py        FastAPI: serves the phone app at /, the desktop page at /classic, API at /api/v2
app/beta_api.py    phone API (Starlette sub-app)
app/db.py, coach.py, adapt.py, ingest.py, demo.py, scheduler.py   storage, rules, weekly adaptation, importers, demo data, scheduled jobs
app/autopilot.py   autonomous daily agent: triggers, guarded tools, versioned changes, undo
static/app/        the phone app (PWA)
static/index.html  the earlier desktop page
data/              fallback dataset
tests/
```

## Not medical advice
The app gives coaching guidance only. The safety rules are conservative defaults; have a clinician review them before you put this in front of real users, especially minors.

## Put it online for judges (Render, free)

1. Push this folder to GitHub (the `.gitignore` keeps `.env` and the database out).
2. On render.com: **New → Blueprint**, pick the repo. It reads `render.yaml`.
3. When asked, paste your `ANTHROPIC_API_KEY` into Render (never into GitHub).
4. After the build you get `https://fitplan-pro-xxxx.onrender.com`. That is the live link.
   Open it on a phone and use Share → Add to Home Screen to install it like an app.
   The free plan sleeps after 15 minutes idle, so open it a minute before judging. Data resets on redeploy.

## Proof of a run

- `python -m tools.trace` replays one person end to end with every agent step timestamped (mock model, free).
- `python -m tools.trace --real` does the same with real Claude calls (a few cents). The log goes to `evals/trace_*.log`.
- `python -m tools.bench --plans 5 --safety` gives real-model timing, token and quality numbers.
