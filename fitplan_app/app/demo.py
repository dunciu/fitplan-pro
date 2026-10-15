"""Synthetic recent history so the beta can be demoed without a wearable (scenarios mirror the training data)."""
import datetime as dt
import random

SCENARIOS = {
    "steady": "Well recovered, good sleep",
    "overreaching": "HRV drifting down, resting HR up, sleep shrinking",
    "poor_sleep": "Two weeks of short sleep",
    "illness": "Sudden resting-HR spike and HRV crash",
}


def seed(scenario: str, end: dt.date, planned: dict[str, dict] | None = None, seed_val: int = 11) -> dict[str, dict]:
    rnd = random.Random(seed_val)
    planned = planned or {}
    out = {}
    for i in range(28):
        d = end - dt.timedelta(days=27 - i)
        ramp = max(0.0, (i - 13) / 14)
        hrv, rhr, sl = rnd.gauss(70, 4), rnd.gauss(55, 1.2), rnd.gauss(7.5, .4)
        sore, done_p = int(max(1, min(10, rnd.gauss(4, 1.2)))), 0.9
        if scenario == "overreaching":
            hrv *= 1 - .28 * ramp; rhr += 7 * ramp; sl -= 1.1 * ramp; sore = int(min(10, sore + 4 * ramp)); done_p = .95
        elif scenario == "poor_sleep" and i >= 14:
            sl = rnd.gauss(5.6, .4); hrv *= .93
        elif scenario == "illness" and i >= 25:
            hrv *= .6; rhr += 11; sl -= .8; sore = min(10, sore + 3); done_p = .2
        row = dict(hrv=round(max(hrv, 15), 1), rhr=round(rhr), sleep_h=round(max(3.0, min(sl, 11)), 2),
                   steps=int(max(2500, rnd.gauss(9000, 2000))), soreness=sore, mood=int(max(1, min(5, rnd.gauss(3.6, .8)))),
                   source="demo")
        if d.isoformat() in planned and d <= end:
            row["done"] = 1 if rnd.random() < done_p else 0
        out[d.isoformat()] = row
    return out
