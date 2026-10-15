"""SQLite storage for the beta (stdlib only). One file, swap for Postgres later."""
import datetime as dt
import json
import os
import secrets
import sqlite3


def path() -> str:
    return os.getenv("FITPLAN_DB", "fitplan.db")


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(path())
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c


SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, token TEXT UNIQUE NOT NULL, created TEXT,
  profile TEXT, safety TEXT, last_adapt_week TEXT);
CREATE TABLE IF NOT EXISTS plans(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  version INTEGER, created TEXT, start_date TEXT, framework TEXT, weeks TEXT, outline TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS logs(user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, date TEXT NOT NULL,
  sleep_h REAL, rhr REAL, hrv REAL, steps INTEGER, soreness INTEGER, mood INTEGER, effort INTEGER, done INTEGER,
  notes TEXT, source TEXT, PRIMARY KEY(user_id, date));
CREATE TABLE IF NOT EXISTS checkins(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created TEXT, week_index INTEGER, decision TEXT, summary TEXT, markdown TEXT, seen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS actions(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created TEXT, date TEXT, kind TEXT, signature TEXT, triggers TEXT, steps TEXT, message TEXT,
  version_before INTEGER, version_after INTEGER, undone INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS settings(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, autopilot INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  version INTEGER, created TEXT, report TEXT, rating INTEGER, note TEXT);
CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY, user_id INTEGER, created TEXT, kind TEXT, status TEXT, detail TEXT);
"""
LOG_FIELDS = ("sleep_h", "rhr", "hrv", "steps", "soreness", "mood", "effort", "done", "notes", "source")


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def new_user() -> dict:
    token = secrets.token_urlsafe(32)
    with conn() as c:
        cur = c.execute("INSERT INTO users(token, created) VALUES(?,?)", (token, now()))
        return {"id": cur.lastrowid, "token": token}


def user_by_token(token: str):
    if not token:
        return None
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE token=?", (token,)).fetchone()
    return dict(r) if r else None


def get_user(uid: int):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return dict(r) if r else None


def set_profile(uid: int, profile: dict, safety: dict):
    with conn() as c:
        c.execute("UPDATE users SET profile=?, safety=? WHERE id=?", (json.dumps(profile), json.dumps(safety), uid))


def set_last_adapt(uid: int, week_key: str):
    with conn() as c:
        c.execute("UPDATE users SET last_adapt_week=? WHERE id=?", (week_key, uid))


def save_plan(uid: int, start_date: str, framework: str, weeks: list, outline: list, note: str = "") -> int:
    with conn() as c:
        v = (c.execute("SELECT COALESCE(MAX(version),0) FROM plans WHERE user_id=?", (uid,)).fetchone()[0]) + 1
        c.execute("INSERT INTO plans(user_id,version,created,start_date,framework,weeks,outline,note) VALUES(?,?,?,?,?,?,?,?)",
                  (uid, v, now(), start_date, framework, json.dumps(weeks), json.dumps(outline), note))
    return v


def active_plan(uid: int):
    with conn() as c:
        r = c.execute("SELECT * FROM plans WHERE user_id=? ORDER BY version DESC LIMIT 1", (uid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["weeks"], d["outline"] = json.loads(d["weeks"]), json.loads(d["outline"])
    return d


def upsert_log(uid: int, date: str, **fields):
    f = {k: v for k, v in fields.items() if k in LOG_FIELDS and v is not None}
    cols = ["user_id", "date"] + list(f)
    sets = ", ".join(f"{k}=COALESCE(excluded.{k}, logs.{k})" for k in f) or "date=date"
    sql = (f"INSERT INTO logs({', '.join(cols)}) VALUES({', '.join('?' * len(cols))}) "
           f"ON CONFLICT(user_id,date) DO UPDATE SET {sets}")
    with conn() as c:
        c.execute(sql, [uid, date] + list(f.values()))


def get_logs(uid: int, start: str, end: str) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM logs WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date", (uid, start, end)).fetchall()
    return [dict(r) for r in rows]


def count_logs(uid: int) -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM logs WHERE user_id=?", (uid,)).fetchone()[0]


def add_checkin(uid: int, week_index: int, decision: str, summary: dict, markdown: str) -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO checkins(user_id,created,week_index,decision,summary,markdown) VALUES(?,?,?,?,?,?)",
                        (uid, now(), week_index, decision, json.dumps(summary), markdown))
        return cur.lastrowid


def list_checkins(uid: int, limit: int = 20) -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM checkins WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["summary"] = json.loads(d["summary"] or "{}")
        out.append(d)
    return out


def mark_seen(uid: int):
    with conn() as c:
        c.execute("UPDATE checkins SET seen=1 WHERE user_id=?", (uid,))


def unseen_count(uid: int) -> int:
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM checkins WHERE user_id=? AND seen=0", (uid,)).fetchone()[0]


def log_run(uid, kind: str, status: str, detail: str = ""):
    with conn() as c:
        c.execute("INSERT INTO runs(user_id,created,kind,status,detail) VALUES(?,?,?,?,?)", (uid, now(), kind, status, detail[:500]))


def users_with_plans() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT u.* FROM users u WHERE EXISTS (SELECT 1 FROM plans p WHERE p.user_id=u.id)").fetchall()
    return [dict(r) for r in rows]


def delete_user(uid: int):
    with conn() as c:
        c.execute("DELETE FROM runs WHERE user_id=?", (uid,))
        c.execute("DELETE FROM users WHERE id=?", (uid,))


def plan_version(uid: int, version: int):
    with conn() as c:
        r = c.execute("SELECT * FROM plans WHERE user_id=? AND version=?", (uid, version)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["weeks"], d["outline"] = json.loads(d["weeks"]), json.loads(d["outline"])
    return d


def add_action(uid: int, date: str, kind: str, signature: str, triggers: list, steps: list, message: str,
               before, after) -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO actions(user_id,created,date,kind,signature,triggers,steps,message,version_before,version_after) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)", (uid, now(), date, kind, signature, json.dumps(triggers),
                                                         json.dumps(steps, default=str), message, before, after))
        return cur.lastrowid


def _action(r):
    d = dict(r)
    d["triggers"], d["steps"] = json.loads(d["triggers"] or "[]"), json.loads(d["steps"] or "[]")
    return d


def list_actions(uid: int, limit: int = 30, date: str | None = None) -> list[dict]:
    q, args = "SELECT * FROM actions WHERE user_id=?", [uid]
    if date:
        q, args = q + " AND date=?", args + [date]
    with conn() as c:
        rows = c.execute(q + " ORDER BY id DESC LIMIT ?", args + [limit]).fetchall()
    return [_action(r) for r in rows]


def get_action(uid: int, aid: int):
    with conn() as c:
        r = c.execute("SELECT * FROM actions WHERE user_id=? AND id=?", (uid, aid)).fetchone()
    return _action(r) if r else None


def mark_undone(aid: int):
    with conn() as c:
        c.execute("UPDATE actions SET undone=1 WHERE id=?", (aid,))


def autopilot_on(uid: int) -> bool:
    with conn() as c:
        r = c.execute("SELECT autopilot FROM settings WHERE user_id=?", (uid,)).fetchone()
    return True if r is None else bool(r[0])


def set_autopilot(uid: int, on: bool):
    with conn() as c:
        c.execute("INSERT INTO settings(user_id, autopilot) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET autopilot=excluded.autopilot",
                  (uid, int(on)))


def save_report(uid: int, version: int, report: dict) -> int:
    with conn() as c:
        return c.execute("INSERT INTO reports(user_id,version,created,report) VALUES(?,?,?,?)",
                         (uid, version, now(), json.dumps(report))).lastrowid


def latest_report(uid: int):
    with conn() as c:
        r = c.execute("SELECT * FROM reports WHERE user_id=? ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["report"] = json.loads(d["report"])
    return d


def rate_report(uid: int, rating: int, note: str = ""):
    with conn() as c:
        c.execute("UPDATE reports SET rating=?, note=? WHERE id=(SELECT id FROM reports WHERE user_id=? ORDER BY id DESC LIMIT 1)",
                  (rating, note[:300], uid))
