"""Benchmark with the REAL model (needs ANTHROPIC_API_KEY). Costs API credits.

  python -m tools.bench --plans 10            # generate N plans from varied profiles, record quality + timing
  python -m tools.bench --safety              # run the two-layer safety screen on the held-out sets
  python -m tools.bench --plans 5 --safety    # both

Writes evals/bench_<timestamp>.csv and prints a markdown summary. Rate each plan afterwards (ok / not ok)
in the CSV's 'human_ok' column to get your human pass rate alongside the automatic metrics."""
import argparse
import asyncio
import csv
import datetime as dt
import os
import statistics as st
import time

from app.llm import AnthropicLLM
from app.pipeline import run_pipeline
from app.safety import screen, screen_with_model
from app.schemas import Profile
from tools.evals import HELD_OUT, TUNING

PROFILES = [
    dict(goal="run my first 5K", age=28, experience="beginner", weeks=8, days_per_week=3),
    dict(goal="run a half marathon", age=34, experience="intermediate", weeks=12, days_per_week=4, injuries="old ankle sprain"),
    dict(goal="swim 1500 m open water", age=41, experience="beginner", weeks=10, days_per_week=3, equipment="pool"),
    dict(goal="get stronger at home", age=30, experience="beginner", weeks=8, days_per_week=3, equipment="dumbbells and bands"),
    dict(goal="badminton season prep", age=22, experience="intermediate", weeks=8, days_per_week=4),
    dict(goal="run a half marathon", age=15, experience="beginner", weeks=12, days_per_week=4),
    dict(goal="build muscle", age=26, experience="intermediate", weeks=12, days_per_week=5, equipment="full gym"),
    dict(goal="sprint triathlon", age=38, experience="intermediate", weeks=12, days_per_week=5, equipment="pool, bike"),
    dict(goal="walk 10K steps and feel fitter", age=63, experience="beginner", weeks=8, days_per_week=3),
    dict(goal="run a 10K under 50 minutes", age=31, experience="advanced", weeks=10, days_per_week=5),
]


async def bench_plans(n: int):
    rows = []
    for i in range(n):
        p = Profile(**PROFILES[i % len(PROFILES)])
        llm, t0, t_draft, final, err = AnthropicLLM(), time.monotonic(), None, None, ""
        try:
            async for ev in run_pipeline(p, llm):
                if ev["stage"] == "draft":
                    t_draft = time.monotonic() - t0
                if ev["stage"] == "final":
                    final = ev
        except Exception as e:
            err = str(e)[:200]
        rep = (final or {}).get("report") or {}
        ch = rep.get("checks", {})
        rows.append(dict(i=i + 1, goal=p.goal, age=p.age, weeks=p.weeks, ok=bool(final) and not err, error=err,
                         s_first_plan=round(t_draft or 0, 1), s_total=round(time.monotonic() - t0, 1),
                         calls=rep.get("model_calls"), in_tokens=(rep.get("tokens") or {}).get("input_tokens"),
                         out_tokens=(rep.get("tokens") or {}).get("output_tokens"),
                         first_pass_errors=ch.get("first_pass_errors"), retries=ch.get("retries"), parse_failures=ch.get("parse_failures"),
                         final_errors=ch.get("final_errors"), critic_high=(rep.get("critic") or {}).get("issues", {}).get("high"),
                         critic_medium=(rep.get("critic") or {}).get("issues", {}).get("medium"),
                         rebuilt_blocks=rep.get("rebuilt_blocks"), editor_rewrite=rep.get("editor_rewrite"), human_ok=""))
        print(f"plan {i + 1}/{n}: {'ok' if rows[-1]['ok'] else 'FAILED ' + err} in {rows[-1]['s_total']} s")
    return rows


async def bench_safety():
    llm, out = AnthropicLLM(), []
    for name, cases in (("tuning", TUNING), ("held_out", HELD_OUT)):
        for kw, want in cases:
            p = Profile(**kw)
            k = screen(p).level == "hold"
            m = (await screen_with_model(p, llm)).level == "hold"
            out.append(dict(set=name, note=kw["notes"], expected=want, keyword_hold=k, two_layer_hold=m))
    return out


def summary(plans, safety):
    md = []
    if plans:
        ok = [r for r in plans if r["ok"]]
        q = lambda k: [r[k] for r in ok if r[k] is not None]
        md += ["## Plans", f"- Completed: {len(ok)}/{len(plans)}",
               f"- Time to first usable plan: median {st.median(q('s_first_plan')):.0f} s" if ok else "",
               f"- Time to reviewed plan: median {st.median(q('s_total')):.0f} s, max {max(q('s_total')):.0f} s" if ok else "",
               f"- Blocks with errors on first try (repaired automatically): {sum(q('first_pass_errors'))}" if ok else "",
               f"- Plans with errors left after repair: {sum(1 for r in ok if r['final_errors'])}/{len(ok)}" if ok else "",
               f"- Critic: {sum(q('critic_high'))} high, {sum(q('critic_medium'))} medium issues; editor rewrite in "
               f"{sum(1 for r in ok if r['editor_rewrite'])}/{len(ok)} plans" if ok else "",
               f"- Tokens per plan: median {st.median(q('in_tokens')):.0f} in / {st.median(q('out_tokens')):.0f} out" if ok else ""]
    if safety:
        for name in ("tuning", "held_out"):
            rs = [r for r in safety if r["set"] == name]
            flags = [r for r in rs if r["expected"] == "hold"]
            safe = [r for r in rs if r["expected"] == "ok"]
            md += [f"## Safety ({name})",
                   f"- Red flags caught: keyword {sum(r['keyword_hold'] for r in flags)}/{len(flags)}, "
                   f"two-layer {sum(r['two_layer_hold'] for r in flags)}/{len(flags)}",
                   f"- False alarms on safe notes: keyword {sum(r['keyword_hold'] for r in safe)}/{len(safe)}, "
                   f"two-layer {sum(r['two_layer_hold'] for r in safe)}/{len(safe)}"]
    return "\n".join(x for x in md if x)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plans", type=int, default=0)
    ap.add_argument("--safety", action="store_true")
    a = ap.parse_args()
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("Set ANTHROPIC_API_KEY first. This benchmark uses the real model.")
    plans = await bench_plans(a.plans) if a.plans else []
    safety = await bench_safety() if a.safety else []
    os.makedirs("evals", exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    for name, rows in (("plans", plans), ("safety", safety)):
        if rows:
            with open(f"evals/bench_{name}_{stamp}.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
    md = summary(plans, safety)
    with open(f"evals/bench_{stamp}.md", "w") as fh:
        fh.write(md + "\n")
    print(md)


if __name__ == "__main__":
    asyncio.run(main())
