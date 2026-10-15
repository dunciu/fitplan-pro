import asyncio
import datetime as dt
import os
import tempfile
import urllib.parse

os.environ["FITPLAN_MOCK"] = "1"
os.environ["FITPLAN_DB"] = os.path.join(tempfile.mkdtemp(), "sync.db")

from app import db, sync

db.init()
sync.init()


def test_parse_simple_format():
    r = sync.parse_push({"days": [{"date": "2026-10-15", "hrv": 61, "rhr": 54, "sleep_h": 7.1, "steps": 9100},
                                  {"date": "2026-10-14", "hrv": 999}]})
    assert r["days"]["2026-10-15"] == {"hrv": 61.0, "rhr": 54.0, "sleep_h": 7.1, "steps": 9100}
    assert "2026-10-14" not in r["days"] and r["dropped"] == 1


def test_parse_health_auto_export_aggregated():
    payload = {"data": {"metrics": [
        {"name": "heart_rate_variability", "units": "ms", "data": [{"date": "2026-10-15 03:10:00 +0100", "qty": 44},
                                                                   {"date": "2026-10-15 05:10:00 +0100", "qty": 50}]},
        {"name": "resting_heart_rate", "units": "count/min", "data": [{"date": "2026-10-15 00:00:00 +0100", "qty": 57}]},
        {"name": "step_count", "units": "count", "data": [{"date": "2026-10-15 12:00:00 +0100", "qty": 4000},
                                                          {"date": "2026-10-15 18:00:00 +0100", "qty": 3500}]},
        {"name": "sleep_analysis", "units": "hr", "data": [{"date": "2026-10-15", "totalSleep": 6.4, "asleep": 6.1, "inBed": 7.2}]},
        {"name": "vo2_max", "units": "ml/kg/min", "data": [{"date": "2026-10-15", "qty": 45}]},
    ]}}
    d = sync.parse_push(payload)["days"]["2026-10-15"]
    assert d == {"hrv": 47.0, "rhr": 57.0, "steps": 7500, "sleep_h": 6.4}


def test_parse_health_auto_export_unaggregated_sleep():
    payload = {"data": {"metrics": [{"name": "sleep_analysis", "units": "hr", "data": [
        {"startDate": "2026-10-14 23:30:00 +0100", "endDate": "2026-10-15 02:00:00 +0100", "qty": 2.5, "value": "Core"},
        {"startDate": "2026-10-15 02:00:00 +0100", "endDate": "2026-10-15 03:00:00 +0100", "qty": 1.0, "value": "Deep"},
        {"startDate": "2026-10-15 03:00:00 +0100", "endDate": "2026-10-15 03:20:00 +0100", "qty": 0.3, "value": "Awake"},
        {"startDate": "2026-10-15 03:20:00 +0100", "endDate": "2026-10-15 06:20:00 +0100", "qty": 3.0, "value": "REM"}]}]}}
    assert sync.parse_push(payload)["days"]["2026-10-15"]["sleep_h"] == 6.5


def test_parse_rejects_garbage():
    try:
        sync.parse_push({"hello": 1})
    except ValueError:
        return
    raise AssertionError


def test_sync_key_rotation():
    u = db.new_user()
    k1 = sync.sync_key(u["id"])
    assert sync.sync_key(u["id"]) == k1 and sync.user_for_key(k1) == u["id"]
    k2 = sync.sync_key(u["id"], rotate=True)
    assert k2 != k1 and sync.user_for_key(k1) is None and sync.user_for_key(k2) == u["id"]


def test_whoop_mapping_uses_wake_day_and_skips_naps():
    sleeps = [{"id": "s1", "start": "2026-10-14T22:40:00.000Z", "end": "2026-10-15T05:50:00.000Z", "timezone_offset": "+01:00",
               "nap": False, "score_state": "SCORED", "score": {"stage_summary": {"total_light_sleep_time_milli": 12_600_000,
               "total_slow_wave_sleep_time_milli": 5_400_000, "total_rem_sleep_time_milli": 5_400_000, "total_in_bed_time_milli": 26_000_000}}},
              {"id": "nap", "start": "2026-10-15T13:00:00.000Z", "end": "2026-10-15T13:30:00.000Z", "timezone_offset": "+01:00",
               "nap": True, "score_state": "SCORED", "score": {"stage_summary": {"total_light_sleep_time_milli": 1_800_000}}},
              {"id": "late", "start": "2026-10-15T23:30:00.000Z", "end": "2026-10-16T23:30:00.000Z", "timezone_offset": "-05:00",
               "nap": False, "score_state": "PENDING_SCORE"}]
    recs = [{"sleep_id": "s1", "score_state": "SCORED", "score": {"recovery_score": 44, "resting_heart_rate": 58, "hrv_rmssd_milli": 41.37}},
            {"sleep_id": "late", "score_state": "SCORED", "score": {"resting_heart_rate": 50, "hrv_rmssd_milli": 70}}]
    days = sync.map_whoop(recs, sleeps)
    assert days == {"2026-10-15": {"sleep_h": 6.5, "hrv": 41.4, "rhr": 58.0}}


def test_whoop_auth_url_has_state_and_offline_scope():
    os.environ.update(WHOOP_CLIENT_ID="cid", WHOOP_CLIENT_SECRET="sec", WHOOP_REDIRECT_URI="https://x.test/api/v2/connect/whoop/callback")
    u = db.new_user()
    url = sync.whoop_auth_url(u["id"])
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert url.startswith(sync.WHOOP_AUTH) and len(q["state"][0]) >= 8 and "offline" in q["scope"][0].split()
    assert sync.user_for_state("whoop", q["state"][0]) == u["id"]
    for k in ("WHOOP_CLIENT_ID", "WHOOP_CLIENT_SECRET", "WHOOP_REDIRECT_URI"):
        os.environ.pop(k)


# --- Google Health (Fitbit Air) -------------------------------------------------------------------------------------
def test_google_mapping_tolerates_documented_shapes():
    points = {
        "daily-resting-heart-rate": [
            {"name": "x/1", "dailyRestingHeartRate": {"date": {"year": 2026, "month": 10, "day": 15}, "beatsPerMinute": "57"}},
            {"name": "x/2", "dailyRestingHeartRate": {"date": {"year": 2026, "month": 10, "day": 14}, "beatsPerMinute": "300"}}],
        "daily-heart-rate-variability": [
            {"dailyHeartRateVariability": {"date": {"year": 2026, "month": 10, "day": 15}, "averageRmssdMilliseconds": 41.26}}],
        "sleep": [
            {"sleep": {"interval": {"startTime": "2026-10-14T22:00:00Z", "startUtcOffset": "3600s",
                                    "endTime": "2026-10-15T05:30:00Z", "endUtcOffset": "3600s"},
                       "type": "STAGES", "stages": [
                           {"startTime": "2026-10-14T22:00:00Z", "endTime": "2026-10-15T01:00:00Z", "type": "LIGHT"},
                           {"startTime": "2026-10-15T01:00:00Z", "endTime": "2026-10-15T01:30:00Z", "type": "AWAKE"},
                           {"startTime": "2026-10-15T01:30:00Z", "endTime": "2026-10-15T03:30:00Z", "type": "DEEP"},
                           {"startTime": "2026-10-15T03:30:00Z", "endTime": "2026-10-15T05:30:00Z", "type": "REM"}]}},
            {"sleep": {"interval": {"startTime": "2026-10-15T13:00:00Z", "endTime": "2026-10-15T13:40:00Z", "endUtcOffset": "3600s"},
                       "summary": {"minutesAsleep": "35"}}}],
    }
    days = sync.map_google(points)
    assert days["2026-10-15"] == {"rhr": 57.0, "hrv": 41.3, "sleep_h": 7.0}     # 3 + 2 + 2 h asleep; nap ignored
    assert "2026-10-14" not in days                                              # 300 bpm dropped as implausible


def test_google_sleep_late_night_offset_gives_wake_day():
    p = {"sleep": {"interval": {"startTime": "2026-10-15T03:00:00Z", "endTime": "2026-10-15T11:00:00Z", "endUtcOffset": "-25200s"},
                   "summary": {"minutesAsleep": "450"}}}
    assert sync.map_google({"sleep": [p]}) == {"2026-10-15": {"sleep_h": 7.5}}


def test_google_auth_url():
    os.environ.update(GOOGLE_CLIENT_ID="gid", GOOGLE_CLIENT_SECRET="gs", GOOGLE_REDIRECT_URI="http://localhost:8000/api/v2/connect/google/callback")
    u = db.new_user()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(sync.google_auth_url(u["id"])).query)
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert "https://www.googleapis.com/auth/googlehealth.sleep.readonly" in q["scope"][0].split()
    assert sync.user_for_state("google", q["state"][0]) == u["id"]
    for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI"):
        os.environ.pop(k)


def test_pairing_codes():
    u = db.new_user()
    code = sync.pair_create(u["id"])
    assert len(code) == 6 and all(ch in sync.PAIR_ALPHABET for ch in code)
    assert sync.pair_claim(code.lower()) == u["token"]
    assert sync.pair_claim(code) is None            # single use
    assert sync.pair_claim("ZZZZZZ") is None
