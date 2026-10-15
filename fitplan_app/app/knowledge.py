"""Loads training examples + rubric from GitHub (FITPLAN_DATA_REPO) with a local fallback in ./data.

FITPLAN_DATA_REPO format:  owner/repo[@branch][:subdir]
  e.g.  dunhuahua/fitplan-data@main:fitplan_training_data
Public repos only (raw.githubusercontent.com). For a private repo set GITHUB_TOKEN.
"""
import json
import os
from pathlib import Path


LOCAL = Path(__file__).resolve().parent.parent / "data"
_cache: dict = {}


def _parse_repo(spec: str):
    subdir = ""
    if ":" in spec:
        spec, subdir = spec.split(":", 1)
    branch = "main"
    if "@" in spec:
        spec, branch = spec.split("@", 1)
    return spec, branch, subdir.strip("/")


def _fetch_github(name: str) -> str | None:
    spec = os.getenv("FITPLAN_DATA_REPO", "").strip()
    if not spec:
        return None
    repo, branch, subdir = _parse_repo(spec)
    path = f"{subdir}/{name}" if subdir else name
    url = f"https://raw.githubusercontent.com/{repo}/{branch}/{path}"
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.getenv("GITHUB_TOKEN") else {}
    try:
        import httpx
        r = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _read(name: str):
    """Return (text, source) where source says where it came from."""
    if name in _cache:
        return _cache[name]
    text = _fetch_github(name)
    source = "github" if text else "local"
    if not text:
        p = LOCAL / name
        text = p.read_text() if p.exists() else ""
        if not text:
            source = "missing"
    _cache[name] = (text, source)
    return _cache[name]


def source_info() -> dict:
    _, s1 = _read("train.jsonl")
    _, s2 = _read("RUBRIC.md")
    return {"repo": os.getenv("FITPLAN_DATA_REPO", "") or None, "train": s1, "rubric": s2}


def rubric() -> str:
    return _read("RUBRIC.md")[0]


def goal_kind(goal: str) -> str:
    g = goal.lower()
    if any(k in g for k in ("run", "marathon", "10k", "5k", "swim", "triathlon", "cycl", "bike", "row")):
        return "endurance"
    if any(k in g for k in ("fat", "weight", "lean", "slim")):
        return "fat_loss"
    if any(k in g for k in ("muscle", "hypertrophy", "bulk")):
        return "hypertrophy"
    if any(k in g for k in ("strength", "lift", "squat", "deadlift")):
        return "strength"
    if any(k in g for k in ("return", "back after", "comeback")):
        return "return"
    return "general"


def examples(goal: str, limit: int = 3, max_chars: int = 1800) -> str:
    """Pick a few worked examples as style/quality references (intake + adversarial + one check-in)."""
    text, _ = _read("train.jsonl")
    rows = []
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not rows:
        return ""
    kind = goal_kind(goal)
    intake = [r for r in rows if r["task"] == "intake" and r["persona"]["goal_kind"] == kind and not r["persona"]["red_flags"]]
    checkin = [r for r in rows if r["task"] == "weekly_checkin" and r.get("label") in ("deload", "reduce_intensity")]
    adv = [r for r in rows if r["task"] == "adversarial"]
    pick = intake[:1] + checkin[:1] + adv[:1]
    out = []
    for r in pick[:limit]:
        user, asst = r["messages"][1]["content"], r["messages"][2]["content"]
        out.append(f"### Example ({r['task']})\nUSER: {user[:600]}\nIDEAL ASSISTANT: {asst[:max_chars]}")
    return "\n\n".join(out)
