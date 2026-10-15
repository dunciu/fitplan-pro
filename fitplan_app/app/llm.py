"""Thin LLM wrapper. Real mode uses the Anthropic API; mock mode (no key needed) returns deterministic demo text."""
import json
import os
import re

MODEL = os.getenv("FITPLAN_MODEL", "claude-sonnet-5-5")


class AnthropicLLM:
    classifies_safety = True

    def __init__(self):
        import anthropic
        self.client = anthropic.AsyncAnthropic()
        self.web_search = os.getenv("FITPLAN_WEB_SEARCH", "0") == "1"
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def _count(self, resp):
        if not hasattr(self, "usage"):
            self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
        self.usage["calls"] += 1
        u = getattr(resp, "usage", None)
        for k in ("input_tokens", "output_tokens"):
            self.usage[k] += int(getattr(u, k, 0) or 0)

    async def complete(self, role: str, system: str, user: str, max_tokens: int = 8000, tool: dict | None = None) -> str:
        kwargs = dict(model=MODEL, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": user}])
        if tool:  # structured output via a tool; tool_choice is left on auto because some models reject forced choice
            kwargs["tools"] = [tool]
            kwargs["system"] = system + f"\n\nReturn your answer by calling the {tool['name']} tool. Do not write the answer as plain text."
        elif role == "research" and self.web_search:
            kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]
        try:
            resp = await self.client.messages.create(**kwargs)
        except Exception:
            if tool or "tools" not in kwargs:
                raise
            kwargs.pop("tools")  # org may not have web search enabled; degrade gracefully
            resp = await self.client.messages.create(**kwargs)
        self._count(resp)
        if tool:
            for b in resp.content:
                if getattr(b, "type", "") == "tool_use":
                    return json.dumps(b.input)
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    async def run_tools(self, system: str, user: str, tools: list[dict], handler, max_turns: int = 8, context=None) -> list[dict]:
        """Agent loop: the model calls tools, `handler(name, input)` executes them (with guardrails) and returns a
        result dict that is sent back, until the model stops calling tools or `finish` is called."""
        messages, transcript = [{"role": "user", "content": user}], []
        for _ in range(max_turns):
            resp = await self.client.messages.create(model=MODEL, max_tokens=2000, system=system, tools=tools, messages=messages)
            self._count(resp)
            blocks, results, finished = [], [], False
            for b in resp.content:
                t = getattr(b, "type", "")
                if t == "text":
                    blocks.append({"type": "text", "text": b.text})
                    if b.text.strip():
                        transcript.append({"tool": "thought", "input": {"text": b.text.strip()[:600]}, "result": None})
                elif t == "tool_use":
                    blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                    res = handler(b.name, b.input)
                    transcript.append({"tool": b.name, "input": b.input, "result": res})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(res),
                                    "is_error": not res.get("ok", False)})
                    finished = finished or (b.name == "finish" and res.get("ok"))
            messages.append({"role": "assistant", "content": blocks})
            if not results or finished:
                break
            messages.append({"role": "user", "content": results})
        return transcript


# --- Mock mode ------------------------------------------------------------------------------------------
_PATTERNS = {  # days/week -> (days, session types, share of weekly minutes)
    2: (["Wed", "Sat"], ["quality", "long"], [.4, .6]),
    3: (["Tue", "Thu", "Sat"], ["easy", "quality", "long"], [.27, .30, .43]),
    4: (["Mon", "Tue", "Thu", "Sat"], ["easy", "quality", "easy", "long"], [.2, .25, .2, .35]),
    5: (["Mon", "Tue", "Thu", "Fri", "Sat"], ["easy", "quality", "easy", "strength", "long"], [.18, .22, .15, .15, .30]),
    6: (["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], ["easy", "quality", "easy", "strength", "easy", "long"], [.15, .2, .15, .12, .12, .26]),
    7: (["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], ["easy", "quality", "easy", "strength", "easy", "easy", "long"], [.12, .18, .12, .12, .1, .12, .24]),
}


def _mock_block(user: str) -> str:
    days = int(re.search(r"DAYS=(\d+)", user).group(1))
    targets = json.loads(re.search(r"WEEK_TARGETS=(\[.*\])", user).group(1))
    dnames, types, shares = _PATTERNS[days]
    weeks = []
    for t in targets:
        mins = [round(t["minutes"] * s) for s in shares]
        mins[-1] += t["minutes"] - sum(mins)  # make the total match exactly
        ss = []
        for d, ty, m in zip(dnames, types, mins):
            ty2 = "easy" if (ty == "quality" and (t["deload"] or t["taper"])) else ty
            ss.append({"day": d, "type": ty2, "title": f"Demo {ty2} session", "minutes": m,
                       "effort": "RPE 3-4, you can hold a conversation" if ty2 != "quality" else "RPE 6-7, comfortably hard",
                       "details": ["Warm-up: 5 min easy", f"Main: {max(m - 10, 5)} min at the stated effort", "Cool-down: 5 min easy"],
                       "why": "Demo session (mock mode)"})
        weeks.append({"week": t["week"], "focus": f"{t['phase']} week (demo)", "sessions": ss, "notes": ""})
    return json.dumps({"weeks": weeks})


class MockLLM:
    """Offline stand-in so the whole app (and tests) run without an API key."""

    def __init__(self):
        self.calls: list[str] = []
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    async def complete(self, role: str, system: str, user: str, max_tokens: int = 0, tool: dict | None = None) -> str:
        self.calls.append(role)
        self.usage["calls"] += 1
        if role == "research":
            return ("Brief: easy aerobic volume, gradual progression, deload every 4th week, sleep and fuelling matter.\n"
                    "---DRAFT---\n## Snapshot\n(mock mode demo)\n\n## Principles\n- Mostly easy effort.\n\n{{WEEKLY_PLAN}}\n\n"
                    "## Fuel & recovery\n- Eat regular meals.\n\n## Warning signs\n- Chest pain: see a doctor.")
        if role == "block":
            return _mock_block(user)
        if role == "critic":
            n_blocks_seen = self.calls.count("critic")
            issues = [{"severity": "medium", "where": "Week 2", "problem": "Quality session lacks a clear interval structure.",
                       "fix": "Give intervals with durations and rests."}] if n_blocks_seen == 1 else []
            return json.dumps({"verdict": "revise", "issues": issues, "strengths": ["Clear structure"]})
        if role == "editor":
            return ("## Snapshot\n(mock mode demo)\n\n## Principles\n- Mostly easy effort.\n\n{{WEEKLY_PLAN}}\n\n"
                    "## Fuel & recovery\n- Eat regular meals.\n\n## Warning signs\n- Chest pain: see a doctor.\n\n"
                    "## What I changed after review\n- Added interval structure to flagged week.\n\n"
                    "This is coaching guidance, not medical advice.")
        return "Mock answer: keep effort easy, sleep 8-9 hours, and message me if anything hurts. This is coaching guidance, not medical advice."

    async def run_tools(self, system: str, user: str, tools: list[dict], handler, max_turns: int = 8, context=None) -> list[dict]:
        """Deterministic stand-in for the autopilot agent: ease the first hard session in the window, else trim the
        next session, then finish. Goes through the same guarded handler as the real model."""
        self.calls.append("autopilot")
        transcript, upcoming = [], (context or {}).get("upcoming", [])

        def call(name, inp):
            res = handler(name, inp)
            transcript.append({"tool": name, "input": inp, "result": res})
            return res

        hard = next((s for s in upcoming if s["type"] in ("quality", "long")), None)
        target = hard or (upcoming[0] if upcoming else None)
        if target:
            mins = max(10, int(round(target["minutes"] * (0.6 if hard else 0.75) / 5) * 5))
            call("ease_session", {"date": target["date"], "type": "easy", "minutes": mins, "title": "Easy recovery session",
                                  "effort": "RPE 2-3, very easy", "details": ["5 min walk", f"{max(mins - 10, 5)} min very easy", "5 min mobility"],
                                  "why": "Lower load while you recover"})
        call("finish", {"message": "You flagged a tough day, so I made your next hard session an easy one. "
                                   "Undo it if you feel better than your numbers suggest."})
        return transcript


def get_llm():
    if os.getenv("FITPLAN_MOCK", "") == "1" or not os.getenv("ANTHROPIC_API_KEY"):
        return MockLLM(), True
    return AnthropicLLM(), False
