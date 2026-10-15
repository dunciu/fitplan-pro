"""Importers: Whoop / Oura / Fitbit-style CSV exports and Apple Health export (.zip or export.xml).

Column detection is by keyword, units by magnitude, so slightly different export layouts still work.
Implausible values are dropped (and counted) instead of polluting a person's baseline.
Limits: written against documented/typical layouts, not verified against every real export; Apple sleep from several
sources may be double counted.
"""
import csv
import datetime as dt
import io
import re
import zipfile
from statistics import mean, median
from xml.etree import ElementTree as ET

RANGES = {"sleep_h": (0.5, 16), "rhr": (30, 120), "hrv": (5, 250), "steps": (0, 100000)}
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _num(x):
    try:
        return float(str(x).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _find(headers: list[str], *keys, avoid=()):
    for i, h in enumerate(headers):
        hl = h.lower()
        if any(k in hl for k in keys) and not any(a in hl for a in avoid):
            return i
    return None


def _clean(row: dict, stats: dict) -> dict:
    out = {}
    for k, v in row.items():
        if v is None:
            continue
        lo, hi = RANGES[k]
        if lo <= v <= hi:
            out[k] = round(v, 2)
        else:
            stats["dropped"] += 1
    return out


def parse_csv(text: str) -> dict:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    if len(rows) < 2:
        raise ValueError("The file has no data rows.")
    headers = [h.strip() for h in rows[0]]
    di = _find(headers, "date", "day", "cycle start", "start time", "summary")
    if di is None:
        raise ValueError("Couldn't find a date column. Expected a header like 'date' or 'Cycle start time'.")
    hi = _find(headers, "hrv", "heart rate variability")
    ri = _find(headers, "resting heart", "resting_hr", "lowest_heart", "resting_heart_rate")
    si = _find(headers, "asleep", "sleep_hours", "sleep duration", "total_sleep", "minutes_asleep", "total sleep", avoid=("performance", "need", "debt", "consistency", "efficiency"))
    ti = _find(headers, "steps")
    if hi is None and ri is None and si is None:
        raise ValueError("Couldn't find HRV, resting heart rate or sleep columns in this file.")
    raw = {}
    for r in rows[1:]:
        if len(r) <= di:
            continue
        m = DATE_RE.search(r[di])
        if not m:
            continue
        g = lambda i: _num(r[i]) if i is not None and i < len(r) else None
        raw.setdefault(m.group(1), []).append(dict(hrv=g(hi), rhr=g(ri), sleep=g(si), steps=g(ti)))
    sleeps = [x["sleep"] for v in raw.values() for x in v if x["sleep"] is not None]
    med = median(sleeps) if sleeps else 0
    div = 3600.0 if med > 1000 else 60.0 if med > 24 else 1.0   # seconds / minutes / hours by magnitude
    stats, days = {"dropped": 0}, {}
    for d, items in raw.items():
        agg = {}
        def col(k):
            v = [x[k] for x in items if x[k] is not None]
            return v
        if col("hrv"): agg["hrv"] = mean(col("hrv"))
        if col("rhr"): agg["rhr"] = mean(col("rhr"))
        if col("sleep"): agg["sleep_h"] = sum(col("sleep")) / div
        if col("steps"): agg["steps"] = sum(col("steps"))
        c = _clean(agg, stats)
        if "steps" in c:
            c["steps"] = int(c["steps"])
        if c:
            days[d] = c
    return {"days": days, "dropped": stats["dropped"], "kind": "csv"}


def parse_apple(data: bytes, keep_days: int = 120) -> dict:
    stream = io.BytesIO(data)
    if zipfile.is_zipfile(stream):
        with zipfile.ZipFile(stream) as z:
            name = next((n for n in z.namelist() if n.lower().endswith("export.xml")), None)
            if not name:
                raise ValueError("No export.xml found inside the zip.")
            stream = io.BytesIO(z.read(name))
    else:
        stream.seek(0)
    cutoff = (dt.date.today() - dt.timedelta(days=keep_days)).isoformat()
    agg: dict[str, dict] = {}
    fmt = "%Y-%m-%d %H:%M:%S %z"
    for _, el in ET.iterparse(stream, events=("end",)):
        if el.tag != "Record":
            el.clear()
            continue
        t, end = el.get("type", ""), (el.get("endDate") or "")[:10]
        if end >= cutoff:
            d = agg.setdefault(end, {"hrv": [], "rhr": [], "steps": 0.0, "sleep": 0.0})
            if t == "HKQuantityTypeIdentifierHeartRateVariabilitySDNN" and _num(el.get("value")) is not None:
                d["hrv"].append(_num(el.get("value")))
            elif t == "HKQuantityTypeIdentifierRestingHeartRate" and _num(el.get("value")) is not None:
                d["rhr"].append(_num(el.get("value")))
            elif t == "HKQuantityTypeIdentifierStepCount" and _num(el.get("value")) is not None:
                d["steps"] += _num(el.get("value"))
            elif t == "HKCategoryTypeIdentifierSleepAnalysis" and "Asleep" in (el.get("value") or ""):
                try:
                    s = dt.datetime.strptime(el.get("startDate"), fmt)
                    e = dt.datetime.strptime(el.get("endDate"), fmt)
                    d["sleep"] += max((e - s).total_seconds(), 0) / 3600
                except (TypeError, ValueError):
                    pass
        el.clear()
    stats, days = {"dropped": 0}, {}
    for d, v in agg.items():
        row = {}
        if v["hrv"]: row["hrv"] = mean(v["hrv"])
        if v["rhr"]: row["rhr"] = mean(v["rhr"])
        if v["sleep"]: row["sleep_h"] = v["sleep"]
        if v["steps"]: row["steps"] = v["steps"]
        c = _clean(row, stats)
        if "steps" in c:
            c["steps"] = int(c["steps"])
        if c:
            days[d] = c
    if not days:
        raise ValueError("No usable heart rate, HRV, sleep or step records found in the last %d days." % keep_days)
    return {"days": days, "dropped": stats["dropped"], "kind": "apple"}


def parse_upload(data: bytes, filename: str = "") -> dict:
    name = filename.lower()
    head = data[:4096].lstrip()
    if name.endswith((".zip", ".xml")) or data[:2] == b"PK" or head.startswith(b"<?xml") or b"<HealthData" in head:
        return parse_apple(data)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return parse_csv(text)
