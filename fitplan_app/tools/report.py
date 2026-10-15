"""Usage and outcome metrics from the app's own database (no model calls).
Run:  python -m tools.report            (reads FITPLAN_DB, default fitplan.db)"""
import json
import statistics as st

from app import coach, db


def main():
    with db.conn() as c:
        users = c.execute("SELECT COUNT(*) FROM users WHERE profile IS NOT NULL").fetchone()[0]
        reports = [json.loads(r[0]) | {"rating": r[1]} for r in c.execute("SELECT report, rating FROM reports").fetchall()]
        actions = [dict(r) for r in c.execute("SELECT kind, undone FROM actions").fetchall()]
        checkins = [dict(r) for r in c.execute("SELECT decision FROM checkins").fetchall()]
        logs = c.execute("SELECT user_id, COUNT(*) FROM logs WHERE source='manual' GROUP BY user_id").fetchall()
        errors = c.execute("SELECT kind, COUNT(*) FROM runs WHERE status='error' GROUP BY kind").fetchall()
    out = ["# FitPlan Pro usage report", f"- People with a plan: {users}"]
    if reports:
        tt = [r["timings_s"]["total"] for r in reports if r.get("timings_s")]
        rated = [r["rating"] for r in reports if r["rating"] in (1, -1)]
        out += [f"- Plans generated: {len(reports)}; median generation time {st.median(tt):.0f} s" if tt else f"- Plans generated: {len(reports)}",
                f"- Blocks failing automatic checks on first try: {sum(r['checks']['first_pass_errors'] for r in reports)} "
                f"(repaired before you saw them); plans with errors left: {sum(1 for r in reports if r['checks']['final_errors'])}",
                f"- Critic issues per plan: {st.mean(sum(r['critic']['issues'].values()) for r in reports):.1f}; "
                f"editor rewrite needed in {sum(1 for r in reports if r['editor_rewrite'])}/{len(reports)} plans",
                f"- Plan ratings: {sum(1 for x in rated if x == 1)}/{len(rated)} thumbs up" if rated else "- Plan ratings: none yet"]
    adj = [a for a in actions if a["kind"] == "adjusted"]
    out += [f"- Autopilot: {len(adj)} adjustments, {sum(a['undone'] for a in adj)} undone "
            f"({100 * sum(a['undone'] for a in adj) / len(adj):.0f}% undo rate = how often people disagreed)" if adj else "- Autopilot: no adjustments yet",
            f"- Autopilot escalations to a professional: {sum(1 for a in actions if a['kind'] == 'escalate')}",
            f"- Weekly coach decisions: " + (", ".join(f"{k} {sum(1 for x in checkins if x['decision'] == k)}" for k in coach.LABELS
                                                       if any(x['decision'] == k for x in checkins)) or "none yet"),
            f"- Check-ins logged per person: median {st.median([n for _, n in logs]):.0f}" if logs else "- Check-ins: none yet",
            "- Errors: " + (", ".join(f"{k} {n}" for k, n in errors) or "none")]
    print("\n".join(out))


if __name__ == "__main__":
    main()
