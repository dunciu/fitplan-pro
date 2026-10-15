"""Live sync.

1. PUSH (works today, any device): POST /api/v2/sync/push with `Authorization: Bearer <sync key>`.
   Accepts either our simple format  {"days": [{"date": "2026-10-15", "hrv": 62, "rhr": 54, "sleep_h": 7.2, "steps": 9000}]}
   or Health Auto Export's REST format {"data": {"metrics": [{"name": "...", "units": "...", "data": [{"date": ..., "qty": ...}]}]}}
   (iPhone app that sends Apple Health / Apple Watch data on a schedule).
2. WHOOP (OAuth 2.0, v2 developer API): connect once, then the scheduler pulls recovery, HRV, resting HR and sleep hourly.
   Needs WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, WHOOP_REDIRECT_URI (e.g. https://<host>/api/v2/connect/whoop/callback).
   Written against WHOOP's published docs; not yet tested against a live WHOOP account.
Every sync runs the autopilot for today, so a bad night can change today's session before you open the app.
"""
import datetime as dt
import os
import secrets
import time
import urllib.parse

from . import db
from .ingest import _clean

WHOOP_AUTH = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API = "https://api.prod.whoop.com/developer"
WHOOP_SCOPES = "offline read:recovery read:sleep read:cycles"


# --- storage --------------------------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS sync_keys(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, key TEXT UNIQUE, created TEXT, last_push TEXT);
CREATE TABLE IF NOT EXISTS connections(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, provider TEXT NOT NULL,
  access_token TEXT, refresh_token TEXT, expires_at REAL, state TEXT, last_sync TEXT, status TEXT, PRIMARY KEY(user_id, provider));
"""


def init():
    with db.conn() as c:
        c.executescript(SCHEMA)


def sync_key(uid: int, rotate: bool = False) -> str:
    with db.conn() as c:
        r = c.execute("SELECT key FROM sync_keys WHERE user_id=?", (uid,)).fetchone()
        if r and not rotate:
            return r[0]
        k = "fps_" + secrets.token_urlsafe(24)
        c.execute("INSERT INTO sync_keys(user_id,key,created) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET key=excluded.key, created=excluded.created",
                  (uid, k, db.now()))
        return k


def user_for_key(key: str):
    if not key:
        return None
    with db.conn() as c:
        r = c.execute("SELECT user_id FROM sync_keys WHERE key=?", (key,)).fetchone()
        if r:
            c.execute("UPDATE sync_keys SET last_push=? WHERE user_id=?", (db.now(), r[0]))
    return r[0] if r else None


def last_push(uid: int):
    with db.conn() as c:
        r = c.execute("SELECT last_push FROM sync_keys WHERE user_id=?", (uid,)).fetchone()
    return r[0] if r else None


def get_conn(uid: int, provider: str):
    with db.conn() as c:
        r = c.execute("SELECT * FROM connections WHERE user_id=? AND provider=?", (uid, provider)).fetchone()
    return dict(r) if r else None


def save_conn(uid: int, provider: str, **f):
    cur = get_conn(uid, provider) or {}
    cur.update(f)
    with db.conn() as c:
        c.execute("INSERT INTO connections(user_id,provider,access_token,refresh_token,expires_at,state,last_sync,status) VALUES(?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(user_id,provider) DO UPDATE SET access_token=excluded.access_token, refresh_token=excluded.refresh_token, "
                  "expires_at=excluded.expires_at, state=excluded.state, last_sync=excluded.last_sync, status=excluded.status",
                  (uid, provider, cur.get("access_token"), cur.get("refresh_token"), cur.get("expires_at"), cur.get("state"),
                   cur.get("last_sync"), cur.get("status")))


def delete_conn(uid: int, provider: str):
    with db.conn() as c:
        c.execute("DELETE FROM connections WHERE user_id=? AND provider=?", (uid, provider))


def user_for_state(provider: str, state: str):
    with db.conn() as c:
        r = c.execute("SELECT user_id FROM connections WHERE provider=? AND state=?", (provider, state)).fetchone()
    return r[0] if r else None


def connected(provider: str) -> list[int]:
    with db.conn() as c:
        return [r[0] for r in c.execute("SELECT user_id FROM connections WHERE provider=? AND status='connected'", (provider,)).fetchall()]


# --- push parsing ---------------------------------------------------------------------------------------------
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_push(payload: dict) -> dict:
    """Return {"days": {date: {hrv, rhr, sleep_h, steps}}, "dropped": n}. Raises ValueError for an unusable payload."""
    raw: dict[str, dict] = {}
    if isinstance(payload.get("days"), list):
        for d in payload["days"]:
            date = str(d.get("date", ""))[:10]
            if len(date) == 10:
                raw[date] = {k: _num(d.get(k)) for k in ("hrv", "rhr", "sleep_h", "steps") if d.get(k) is not None}
    else:
        metrics = (payload.get("data") or {}).get("metrics")
        if not isinstance(metrics, list):
            raise ValueError("Expected {'days': [...]} or a Health Auto Export payload with data.metrics.")
        for m in metrics:
            name, units = str(m.get("name", "")).lower(), str(m.get("units", "")).lower()
            key = ("hrv" if "variab" in name else "rhr" if "resting" in name and "heart" in name else
                   "steps" if "step" in name else "sleep_h" if "sleep" in name else None)
            if not key:
                continue
            for p in m.get("data") or []:
                date = str(p.get("date") or p.get("endDate") or p.get("sleepEnd") or "")[:10]
                if len(date) != 10:
                    continue
                row = raw.setdefault(date, {})
                if key == "sleep_h":
                    if "value" in p and p.get("totalSleep") is None:      # unaggregated: one entry per sleep segment
                        if str(p["value"]).lower() not in ("asleep", "core", "deep", "rem"):
                            continue                                       # Awake / In Bed / Unspecified don't count
                        v = (row.get("sleep_h") or 0) + (_num(p.get("qty")) or 0) / (60 if "min" in units else 1)
                        row["sleep_h"] = v
                        continue
                    v = _num(p.get("totalSleep")) or _num(p.get("asleep")) or _num(p.get("qty"))
                    if v is not None and "min" in units:
                        v /= 60
                    if v is not None:
                        row["sleep_h"] = v
                elif key == "steps":
                    row["steps"] = (row.get("steps") or 0) + (_num(p.get("qty")) or 0)
                else:
                    v = _num(p.get("qty")) if p.get("qty") is not None else _num(p.get("Avg"))
                    if v is not None:
                        row.setdefault(f"_{key}", []).append(v)
        for row in raw.values():
            for k in ("hrv", "rhr"):
                vals = row.pop(f"_{k}", None)
                if vals:
                    row[k] = sum(vals) / len(vals)
    stats, days = {"dropped": 0}, {}
    for date, row in raw.items():
        c = _clean({k: v for k, v in row.items() if v is not None}, stats)
        if "steps" in c:
            c["steps"] = int(c["steps"])
        if c:
            days[date] = c
    return {"days": days, "dropped": stats["dropped"]}


def store(uid: int, days: dict, source: str) -> list[str]:
    for date, row in days.items():
        db.upsert_log(uid, date, source=source, **row)
    return sorted(days)


# --- WHOOP ----------------------------------------------------------------------------------------------------
def whoop_configured() -> bool:
    return all(os.getenv(k) for k in ("WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "WHOOP_REDIRECT_URI"))


def whoop_auth_url(uid: int) -> str:
    state = secrets.token_urlsafe(12)            # WHOOP requires at least 8 characters
    save_conn(uid, "whoop", state=state, status="pending")
    q = {"response_type": "code", "client_id": os.environ["WHOOP_CLIENT_ID"], "redirect_uri": os.environ["WHOOP_REDIRECT_URI"],
         "scope": WHOOP_SCOPES, "state": state}
    return WHOOP_AUTH + "?" + urllib.parse.urlencode(q)


async def _token_request(data: dict) -> dict:
    import httpx
    data = dict(data, client_id=os.environ["WHOOP_CLIENT_ID"], client_secret=os.environ["WHOOP_CLIENT_SECRET"])
    async with httpx.AsyncClient(timeout=20) as cl:
        r = await cl.post(WHOOP_TOKEN, data=data)
        r.raise_for_status()
        return r.json()


def _save_tokens(uid: int, tok: dict):
    save_conn(uid, "whoop", access_token=tok["access_token"], refresh_token=tok.get("refresh_token"),
              expires_at=time.time() + int(tok.get("expires_in", 3600)) - 60, status="connected", state=None)


async def whoop_callback(code: str, state: str) -> int:
    uid = user_for_state("whoop", state)
    if not uid:
        raise ValueError("Unknown or expired connection attempt. Try connecting again.")
    tok = await _token_request({"grant_type": "authorization_code", "code": code, "redirect_uri": os.environ["WHOOP_REDIRECT_URI"]})
    _save_tokens(uid, tok)
    return uid


async def _access_token(uid: int) -> str:
    c = get_conn(uid, "whoop")
    if not c or c.get("status") != "connected":
        raise ValueError("WHOOP is not connected.")
    if (c.get("expires_at") or 0) > time.time():
        return c["access_token"]
    # Refresh replaces BOTH tokens; only one refresh may run at a time per user (single scheduler job does this).
    tok = await _token_request({"grant_type": "refresh_token", "refresh_token": c["refresh_token"], "scope": "offline"})
    _save_tokens(uid, tok)
    return tok["access_token"]


async def _collection(client, path: str, token: str, start: str) -> list[dict]:
    out, nxt = [], None
    for _ in range(20):
        params = {"limit": 25, "start": start} | ({"nextToken": nxt} if nxt else {})
        r = await client.get(WHOOP_API + path, params=params, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()
        body = r.json()
        out += body.get("records", [])
        nxt = body.get("next_token")
        if not nxt:
            break
    return out


def map_whoop(recoveries: list[dict], sleeps: list[dict]) -> dict:
    """WHOOP v2 records -> {date: {hrv, rhr, sleep_h}}. Dated by the morning you woke up (sleep end, local offset)."""
    def wake_date(s):
        try:
            end = dt.datetime.fromisoformat(s["end"].replace("Z", "+00:00"))
            off = s.get("timezone_offset") or "+00:00"
            sign = -1 if off.startswith("-") else 1
            hh, mm = (int(x) for x in off.lstrip("+-").split(":"))
            return (end + sign * dt.timedelta(hours=hh, minutes=mm)).date().isoformat()
        except (KeyError, ValueError, AttributeError):
            return None
    days, by_sleep = {}, {}
    for s in sleeps:
        if s.get("nap") or s.get("score_state") != "SCORED":
            continue
        d = wake_date(s)
        if not d:
            continue
        by_sleep[s.get("id")] = d
        st = (s.get("score") or {}).get("stage_summary") or {}
        ms = sum(st.get(k, 0) or 0 for k in ("total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli", "total_rem_sleep_time_milli"))
        if ms:
            days.setdefault(d, {})["sleep_h"] = round(ms / 3_600_000, 2)
    for r in recoveries:
        if r.get("score_state") != "SCORED":
            continue
        d = by_sleep.get(r.get("sleep_id"))
        if not d:
            continue
        sc = r.get("score") or {}
        if sc.get("hrv_rmssd_milli") is not None:
            days.setdefault(d, {})["hrv"] = round(float(sc["hrv_rmssd_milli"]), 1)
        if sc.get("resting_heart_rate") is not None:
            days.setdefault(d, {})["rhr"] = float(sc["resting_heart_rate"])
    stats = {"dropped": 0}
    return {d: _clean(v, stats) for d, v in days.items()}


async def whoop_sync(uid: int, days: int = 14) -> list[str]:
    import httpx
    token = await _access_token(uid)
    start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat().replace("+00:00", "Z")
    async with httpx.AsyncClient(timeout=30) as cl:
        sleeps = await _collection(cl, "/v2/activity/sleep", token, start)
        recs = await _collection(cl, "/v2/recovery", token, start)
    got = store(uid, map_whoop(recs, sleeps), "whoop")
    save_conn(uid, "whoop", last_sync=db.now())
    return got


# --- Google Health API (Fitbit Air, Pixel Watch and other Fitbit devices) -----------------------------------------
# The legacy Fitbit Web API loses support on 30 Sep 2026 and is turned off on 30 Oct 2026, so this uses the
# Google Health API. Needs a Google Cloud project with the Google Health API enabled and a Web OAuth client:
# GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI (https://<host>/api/v2/connect/google/callback, or
# http://localhost:8000/api/v2/connect/google/callback for local testing).
# Written against Google's published docs; response field names are read tolerantly and NOT yet verified against a
# live account. If a value is missing after a real sync, inspect one response and adjust _gh_value().
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GH_API = "https://health.googleapis.com/v4/users/me/dataTypes"
GOOGLE_SCOPES = " ".join("https://www.googleapis.com/auth/googlehealth." + s for s in
                         ("sleep.readonly", "health_metrics_and_measurements.readonly", "activity_and_fitness.readonly"))
GH_TYPES = ("daily-resting-heart-rate", "daily-heart-rate-variability", "sleep")


def google_configured() -> bool:
    return all(os.getenv(k) for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"))


def google_auth_url(uid: int) -> str:
    state = secrets.token_urlsafe(16)
    save_conn(uid, "google", state=state, status="pending")
    q = {"response_type": "code", "client_id": os.environ["GOOGLE_CLIENT_ID"], "redirect_uri": os.environ["GOOGLE_REDIRECT_URI"],
         "scope": GOOGLE_SCOPES, "state": state, "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true"}
    return GOOGLE_AUTH + "?" + urllib.parse.urlencode(q)


async def _google_token(data: dict) -> dict:
    import httpx
    data = dict(data, client_id=os.environ["GOOGLE_CLIENT_ID"], client_secret=os.environ["GOOGLE_CLIENT_SECRET"])
    async with httpx.AsyncClient(timeout=20) as cl:
        r = await cl.post(GOOGLE_TOKEN, data=data)
        r.raise_for_status()
        return r.json()


def _save_google(uid: int, tok: dict):
    prev = get_conn(uid, "google") or {}
    save_conn(uid, "google", access_token=tok["access_token"],
              refresh_token=tok.get("refresh_token") or prev.get("refresh_token"),   # Google often omits it on refresh
              expires_at=time.time() + int(tok.get("expires_in", 3600)) - 60, status="connected", state=None)


async def google_callback(code: str, state: str) -> int:
    uid = user_for_state("google", state)
    if not uid:
        raise ValueError("Unknown or expired connection attempt. Try connecting again.")
    _save_google(uid, await _google_token({"grant_type": "authorization_code", "code": code,
                                           "redirect_uri": os.environ["GOOGLE_REDIRECT_URI"]}))
    return uid


async def _google_access(uid: int) -> str:
    c = get_conn(uid, "google")
    if not c or c.get("status") != "connected":
        raise ValueError("Google Health is not connected.")
    if (c.get("expires_at") or 0) > time.time():
        return c["access_token"]
    if not c.get("refresh_token"):
        raise ValueError("Google sign-in expired. Connect again.")
    tok = await _google_token({"grant_type": "refresh_token", "refresh_token": c["refresh_token"]})
    _save_google(uid, tok)
    return tok["access_token"]


def _walk(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield path + (k,), v
            yield from _walk(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _walk(v, path + (i,))


def _parse_time(s):
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _offset(s) -> dt.timedelta:
    """Google durations look like '-14400s'."""
    try:
        return dt.timedelta(seconds=float(str(s).rstrip("s")))
    except ValueError:
        return dt.timedelta(0)


def _gh_date(p: dict, prefer_end: bool = False):
    """Local calendar date of a data point: a {year, month, day} object, a civil time, or a timestamp + UTC offset."""
    for path, v in _walk(p):
        if path[-1] == "date" and isinstance(v, dict) and {"year", "month", "day"} <= set(v):
            return f"{int(v['year']):04d}-{int(v['month']):02d}-{int(v['day']):02d}"
        if path[-1] == "date" and isinstance(v, str) and len(v) >= 10:
            return v[:10]
    keys = ("civilEndTime", "endTime") if prefer_end else ("civilStartTime", "startTime", "physicalTime")
    for want in keys:
        for path, v in _walk(p):
            if path[-1] == want and isinstance(v, str):
                if want.startswith("civil"):
                    return v[:10]
                t = _parse_time(v)
                if t:
                    parent = p
                    for k in path[:-1]:
                        parent = parent[k]
                    off_key = {"endTime": "endUtcOffset", "startTime": "startUtcOffset", "physicalTime": "utcOffset"}[want]
                    return (t + _offset(parent.get(off_key, "0s"))).date().isoformat()
    return None


def _gh_value(p: dict, keys: tuple):
    for path, v in _walk(p):
        k = str(path[-1]).lower()
        if any(want in k for want in keys) and not isinstance(v, (dict, list)):
            try:
                return float(v)          # int64 values arrive as strings
            except (TypeError, ValueError):
                continue
    return None


def _gh_sleep_hours(p: dict):
    m = _gh_value(p, ("minutesasleep",))
    if m:
        return m / 60
    total = 0.0
    for path, v in _walk(p):
        if path[-1] == "stages" and isinstance(v, list):
            for st in v:
                if str(st.get("type", "")).upper() in ("LIGHT", "DEEP", "REM", "ASLEEP"):
                    a, b = _parse_time(st.get("startTime")), _parse_time(st.get("endTime"))
                    if a and b:
                        total += (b - a).total_seconds() / 3600
            break
    if total:
        return total
    a = b = None
    for path, v in _walk(p):
        if path[-1] == "startTime" and a is None:
            a = _parse_time(v)
        if path[-1] == "endTime" and b is None:
            b = _parse_time(v)
    if a and b:
        awake = _gh_value(p, ("minutesawake",)) or 0
        return (b - a).total_seconds() / 3600 - awake / 60
    return None


def map_google(points: dict) -> dict:
    """{data type: [dataPoint, ...]} -> {date: {rhr, hrv, sleep_h}}. Longest sleep per wake-up date wins (naps lose)."""
    days: dict[str, dict] = {}
    for p in points.get("daily-resting-heart-rate", []):
        d, v = _gh_date(p), _gh_value(p, ("beatsperminute", "bpm"))
        if d and v:
            days.setdefault(d, {})["rhr"] = v
    for p in points.get("daily-heart-rate-variability", []):
        d, v = _gh_date(p), _gh_value(p, ("rmssd",))
        if d and v:
            days.setdefault(d, {})["hrv"] = round(v, 1)
    for p in points.get("sleep", []):
        d, h = _gh_date(p, prefer_end=True), _gh_sleep_hours(p)
        if d and h and h > (days.get(d, {}).get("sleep_h") or 0):
            days.setdefault(d, {})["sleep_h"] = round(h, 2)
    stats = {"dropped": 0}
    return {d: c for d, v in days.items() if (c := _clean(v, stats))}


async def google_sync(uid: int, days: int = 14) -> list[str]:
    import httpx
    token = await _google_access(uid)
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    points: dict[str, list] = {}
    async with httpx.AsyncClient(timeout=30) as cl:
        for t in GH_TYPES:
            got, page = [], None
            for _ in range(10):
                r = await cl.get(f"{GH_API}/{t}/dataPoints", headers={"Authorization": f"Bearer {token}"},
                                 params={"pageSize": 100} | ({"pageToken": page} if page else {}))
                r.raise_for_status()
                body = r.json()
                batch = body.get("dataPoints") or body.get("points") or []
                got += batch
                page = body.get("nextPageToken")
                dates = [d for d in (_gh_date(p) for p in batch) if d]
                if not page or (dates and min(dates) < cutoff):
                    break
            points[t] = got
    mapped = {d: v for d, v in map_google(points).items() if d >= cutoff}
    got = store(uid, mapped, "google")
    save_conn(uid, "google", last_sync=db.now())
    return got


# --- provider registry (routes and scheduler use this) -------------------------------------------------------------
PROVIDERS = {
    "whoop": {"name": "WHOOP", "configured": whoop_configured, "auth_url": whoop_auth_url, "callback": whoop_callback, "sync": whoop_sync},
    "google": {"name": "Google Health", "configured": google_configured, "auth_url": google_auth_url, "callback": google_callback,
               "sync": google_sync},
}


def sync_minutes() -> int:
    return max(15, int(os.getenv("FITPLAN_SYNC_MINUTES", "60")))


# --- device pairing: use the same account on your iPhone -----------------------------------------------------------
PAIR_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def pair_create(uid: int) -> str:
    code = "".join(secrets.choice(PAIR_ALPHABET) for _ in range(6))
    with db.conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS pair_codes(code TEXT PRIMARY KEY, user_id INTEGER, expires REAL)")
        c.execute("DELETE FROM pair_codes WHERE user_id=? OR expires<?", (uid, time.time()))
        c.execute("INSERT INTO pair_codes VALUES(?,?,?)", (code, uid, time.time() + 600))
    return code


def pair_claim(code: str):
    code = (code or "").strip().upper().replace(" ", "").replace("-", "")
    with db.conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS pair_codes(code TEXT PRIMARY KEY, user_id INTEGER, expires REAL)")
        r = c.execute("SELECT user_id FROM pair_codes WHERE code=? AND expires>=?", (code, time.time())).fetchone()
        if not r:
            return None
        c.execute("DELETE FROM pair_codes WHERE code=?", (code,))
        u = c.execute("SELECT token FROM users WHERE id=?", (r[0],)).fetchone()
    return u[0] if u else None
