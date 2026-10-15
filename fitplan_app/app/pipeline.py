"""Orchestrates: safety screen -> RESEARCH (framework + session blocks) -> CRITIC -> targeted fixes -> EDITOR.

Yields progress events for the UI. Weekly numbers come from code (planlint.outline); the LLM writes sessions in
4-week blocks, each block is machine-checked and retried once, and the critic can send individual blocks back.
"""
import asyncio
import json
import re
import time
from typing import AsyncIterator

from . import knowledge, prompts
from .planlint import BLOCK_TOOL, BLOCK_WEEKS, lint_block, outline, outline_table, parse_block, render_weeks
from .safety import Screen, screen, screen_with_model
from .schemas import Profile
from .targets import facts


def _profile_block(p: Profile) -> str:
    # Wrapped in tags so the models treat it as data, never as instructions.
    return "<user_profile>\n" + json.dumps(p.model_dump(), ensure_ascii=False, indent=1) + "\n</user_profile>"


def _constraints_block(s: Screen) -> str:
    return "NON-NEGOTIABLE CONSTRAINTS:\n" + "\n".join(f"- {c}" for c in s.constraints)


def parse_critic(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    data.setdefault("verdict", "revise")  # fail safe: if unparseable, still run the editor
    data.setdefault("issues", [])
    data.setdefault("strengths", [])
    return data


async def _build_block(llm, base: str, framework: str, p: Profile, rows: list[dict], feedback: str = ""):
    """Ask for one block of weeks; lint; retry with the failures (3 attempts). Returns (weeks, lint_issues, stats)."""
    targets = [{k: r[k] for k in ("week", "phase", "minutes", "deload", "taper")} for r in rows]
    for t, r in zip(targets, rows):
        if r.get("no_quality"):
            t["no_quality"] = True
    user = base + (f"\n\nFRAMEWORK (context only):\n{framework[:6000]}" if framework else "") + \
        f"\n\nDAYS={p.days_per_week}\nWEEK_TARGETS={json.dumps(targets)}"
    if feedback:
        user += f"\n\nFIX THESE PROBLEMS FROM REVIEW:\n{feedback}"
    stats = {"attempts": 0, "parse_failures": 0, "first_pass_errors": None}
    last_error = ""
    for attempt in range(3):
        stats["attempts"] += 1
        text = await llm.complete("block", prompts.BLOCK, user, max_tokens=8000, tool=BLOCK_TOOL)
        try:
            weeks = parse_block(text, rows)
        except ValueError as e:
            last_error = str(e)
            stats["parse_failures"] += 1
            user += f"\n\nYour previous reply was unusable ({e}). Return ONLY the JSON object described."
            continue
        issues = lint_block(weeks, rows, p)
        errors = [m for sev, m in issues if sev == "error"]
        if stats["first_pass_errors"] is None:
            stats["first_pass_errors"] = len(errors)
        if not errors or attempt == 2:
            return weeks, issues, stats
        user += "\n\nAUTOMATED CHECKS FAILED on your previous reply; fix all of these:\n" + "\n".join(errors)
    raise ValueError(f"Could not build weeks {rows[0]['week']}-{rows[-1]['week']}: {last_error}")


def _weeks_in(where: str, n: int) -> set[int]:
    found: set[int] = set()
    for m in re.finditer(r"weeks?\s*(\d+)(?:\s*(?:-|–|to|and|&)\s*(\d+))?", where or "", re.I):
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a <= b:
            found.update(w for w in range(a, b + 1) if 1 <= w <= n)
    return found


def _framework_issues(critique: dict) -> list[dict]:
    """High/medium issues that are about the written guide rather than a specific week."""
    return [i for i in critique["issues"] if i.get("severity") in ("high", "medium") and not re.search(r"weeks?\s*\d", i.get("where", ""), re.I)]


async def run_pipeline(profile: Profile, llm) -> AsyncIterator[dict]:
    """Fast path:
      1. research guide and all session blocks run AT THE SAME TIME (blocks only need profile + weekly targets);
      2. a 'draft' event carries a usable plan before review, so the app can open it immediately;
      3. critic reviews; only flagged blocks are rebuilt;
      4. the editor rewrites the guide ONLY if the critic flagged the guide itself (otherwise code writes the change log).
    Every stage is timed and the final event carries a quality report."""
    t0 = time.monotonic()
    timings: dict[str, float] = {}
    lap = lambda k, t: timings.__setitem__(k, round(time.monotonic() - t, 1))

    try:
        s = await screen_with_model(profile, llm)
    except Exception:  # classifier unavailable: keyword layer still applies
        s = screen(profile)
    yield {"stage": "safety", "status": "done", "data": s.as_dict()}
    if s.level == "hold":
        yield {"stage": "final", "status": "hold", "markdown": f"## Let's get you checked first\n\n{s.message}"}
        return

    rows = outline(profile)
    base = f"{_profile_block(profile)}\n\n{_constraints_block(s)}\n\n{facts(profile, s)}"
    refs = knowledge.examples(profile.goal)
    rubric = knowledge.rubric()
    chunks = [rows[i:i + BLOCK_WEEKS] for i in range(0, len(rows), BLOCK_WEEKS)]

    # 1. Research guide + session blocks in parallel ------------------------------------
    yield {"stage": "research", "status": "running", "message": f"writing the guide and {len(rows)} weeks at once"}
    t = time.monotonic()
    r_user = (f"{base}\n\nWEEKLY TARGETS (generated separately; for context):\n{outline_table(rows)}"
              + (f"\n\nREFERENCE EXAMPLES (style/quality only, do not copy):\n{refs}" if refs else ""))
    research, *built = await asyncio.gather(
        llm.complete("research", prompts.RESEARCHER, r_user, max_tokens=8000),
        *[_build_block(llm, base, "", profile, c) for c in chunks])
    lap("research_and_sessions", t)
    brief, _, framework = research.partition("---DRAFT---")
    framework, brief = (framework.strip() or research.strip()), brief.strip()
    if "{{WEEKLY_PLAN}}" not in framework:
        cut = framework.find("## Strength")
        framework = (framework[:cut] + "{{WEEKLY_PLAN}}\n\n" + framework[cut:]) if cut >= 0 else framework + "\n\n{{WEEKLY_PLAN}}"
    blocks = [list(b[0]) for b in built]
    block_issues = [list(b[1]) for b in built]
    block_stats = [b[2] for b in built]
    all_weeks = lambda: sorted((w for b in blocks for w in b), key=lambda w: w["week"])
    n_err = lambda: sum(1 for bi in block_issues for sev, _ in bi if sev == "error")
    n_warn = lambda: sum(1 for bi in block_issues for sev, _ in bi if sev == "warn")
    yield {"stage": "research", "status": "done", "data": {
        "brief": brief, "weeks": len(rows), "automated_warnings": n_warn(), "automated_errors": n_err()}}
    yield {"stage": "draft", "status": "ok", "framework": framework, "weeks": all_weeks(), "outline": rows}

    def assemble() -> str:
        return render_weeks(all_weeks(), rows)

    def lint_text() -> str:
        msgs = [f"{sev.upper()}: {m}" for bi in block_issues for sev, m in bi]
        return "\n".join(msgs) if msgs else "All automated checks passed."

    # 2. Critic ---------------------------------------------------------------------------
    yield {"stage": "critic", "status": "running"}
    t = time.monotonic()
    c_user = (f"{base}\n\nQUALITY RUBRIC:\n{rubric}\n\nAUTOMATED CHECKS:\n{lint_text()}\n\n"
              f"FRAMEWORK:\n{framework}\n\nWEEKLY PLAN:\n{assemble()}")
    critique = parse_critic(await llm.complete("critic", prompts.CRITIC, c_user, max_tokens=3000))
    lap("critic", t)
    yield {"stage": "critic", "status": "done", "data": critique}

    # 3. Targeted rebuild + editor (only when needed), in parallel ---------------------------
    changes: list[str] = []
    per_block: dict[int, list[str]] = {}
    for issue in critique["issues"]:
        if issue.get("severity") in ("high", "medium"):
            for w in _weeks_in(issue.get("where", ""), len(rows)):
                per_block.setdefault((w - 1) // BLOCK_WEEKS, []).append(
                    f"{issue.get('where')}: {issue.get('problem')} Fix: {issue.get('fix')}")
    guide_issues = _framework_issues(critique)
    yield {"stage": "editor", "status": "running",
           "message": " and ".join(x for x in (f"rebuilding {len(per_block)} flagged part(s)" if per_block else "",
                                              "rewriting the guide" if guide_issues else "") if x) or "finishing up"}
    t = time.monotonic()
    idxs = sorted(per_block)
    rebuild = [_build_block(llm, base, framework, profile, chunks[i], "\n".join(dict.fromkeys(per_block[i]))) for i in idxs]
    e_user = (f"{base}\n\nRESEARCH BRIEF:\n{brief}\n\nFRAMEWORK:\n{framework}\n\n"
              f"WEEKLY TARGET TABLE:\n{outline_table(rows)}\n\n"
              f"CRITIC ISSUES ABOUT THE GUIDE (JSON):\n{json.dumps(guide_issues, indent=1)}")
    editor = [llm.complete("editor", prompts.EDITOR, e_user, max_tokens=8000)] if guide_issues else []
    results = await asyncio.gather(*rebuild, *editor)
    for i, (weeks, issues, st) in zip(idxs, results[:len(idxs)]):
        blocks[i], block_issues[i] = list(weeks), list(issues)
        block_stats.append(st)
        changes.append(f"Rebuilt weeks {chunks[i][0]['week']}-{chunks[i][-1]['week']} after the critic flagged: "
                       + "; ".join(dict.fromkeys(x.split(': ', 1)[-1][:90] for x in per_block[i])))
    if guide_issues:
        final = results[-1].strip()
        if "{{WEEKLY_PLAN}}" not in final:
            cut = final.find("## What I changed")
            final = (final[:cut] + "{{WEEKLY_PLAN}}\n\n" + final[cut:]) if cut >= 0 else final + "\n\n{{WEEKLY_PLAN}}"
        if changes and "## What I changed" in final:
            final = final.replace("## What I changed after review", "## What I changed after review\n" + "\n".join(f"- {c}" for c in changes), 1)
    else:  # guide passed review: keep it and add the change log in code (saves a full rewrite)
        log = "\n".join(f"- {c}" for c in changes) or "- The reviewers found nothing that needed changing."
        final = framework.rstrip() + f"\n\n## What I changed after review\n{log}\n\nThis is coaching guidance, not medical advice."
    lap("fixes", t)
    timings["total"] = round(time.monotonic() - t0, 1)
    framework_final = final
    final = final.replace("{{WEEKLY_PLAN}}", "## Week-by-week plan\n\n" + assemble(), 1)
    sev = {k: sum(1 for i in critique["issues"] if i.get("severity") == k) for k in ("high", "medium", "low")}
    report = {
        "timings_s": timings, "weeks": len(rows),
        "model_calls": dict(getattr(llm, "usage", {})).get("calls"), "tokens": {k: v for k, v in getattr(llm, "usage", {}).items() if k != "calls"},
        "checks": {"blocks": len(chunks), "first_pass_errors": sum((st["first_pass_errors"] or 0) for st in block_stats[:len(chunks)]),
                   "retries": sum(st["attempts"] - 1 for st in block_stats), "parse_failures": sum(st["parse_failures"] for st in block_stats),
                   "final_errors": n_err(), "final_warnings": n_warn()},
        "critic": {"verdict": critique.get("verdict"), "issues": sev}, "rebuilt_blocks": len(idxs), "editor_rewrite": bool(guide_issues),
        "changes": changes,
    }
    yield {"stage": "editor", "status": "done"}
    yield {"stage": "final", "status": "ok", "markdown": final, "framework": framework_final,
           "weeks": all_weeks(), "outline": rows, "report": report}


async def followup(question: str, plan: str, age: int, llm) -> str:
    q = Profile(goal=question[:300] if len(question) >= 3 else "general fitness", age=age, notes=question[:800])
    try:
        s = await screen_with_model(q, llm)
    except Exception:
        s = screen(q)
    if s.level == "hold":
        return s.message
    user = f"{_constraints_block(s)}\n\n<plan>\n{plan}\n</plan>\n\n<question>\n{question}\n</question>"
    return (await llm.complete("followup", prompts.FOLLOWUP, user, max_tokens=1500)).strip()
