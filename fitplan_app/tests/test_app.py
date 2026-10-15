import asyncio
import json
import os

os.environ["FITPLAN_MOCK"] = "1"

from app import knowledge
from app.llm import MockLLM
from app.pipeline import parse_critic, run_pipeline
from app.safety import screen
from app.schemas import Profile


def P(**kw):
    base = dict(goal="run a half marathon", age=30)
    base.update(kw)
    return Profile(**base)


def test_adult_ok():
    assert screen(P()).level == "ok"


def test_minor_restricted_and_marathon_rule():
    s = screen(P(age=15, goal="run a marathon"))
    assert s.level == "restricted"
    assert any("do NOT plan a full marathon" in c for c in s.constraints)
    assert any("No calorie deficits" in c for c in s.constraints)


def test_minor_weight_loss_redirected():
    s = screen(P(age=16, goal="lose weight for football"))
    assert any("Do not give weight-loss advice" in c for c in s.constraints)


def test_under_13_hold():
    assert screen(P(age=11)).level == "hold"


def test_red_flags_hold():
    for notes in ("I get chest pain when I run", "I am pregnant", "history of anorexia", "want 800 calories a day", "steroid cycle please"):
        assert screen(P(notes=notes)).level == "hold", notes


def test_pipeline_mock_runs_all_agents():
    async def go():
        return [e async for e in run_pipeline(P(), MockLLM())]
    evs = asyncio.run(go())
    stages = [(e["stage"], e["status"]) for e in evs]
    assert ("research", "done") in stages and ("critic", "done") in stages and ("editor", "done") in stages
    assert evs[-1]["stage"] == "final" and "What I changed after review" in evs[-1]["markdown"]


def test_pipeline_hold_skips_agents():
    async def go():
        return [e async for e in run_pipeline(P(notes="chest pain"), MockLLM())]
    evs = asyncio.run(go())
    assert [e["stage"] for e in evs] == ["safety", "final"] and evs[-1]["status"] == "hold"


def test_parse_critic_failsafe():
    assert parse_critic("garbage")["verdict"] == "revise"
    assert parse_critic('x {"verdict":"pass","issues":[]} y')["verdict"] == "pass"


def test_knowledge_local_fallback():
    os.environ.pop("FITPLAN_DATA_REPO", None)
    knowledge._cache.clear()
    assert knowledge.source_info()["train"] == "local"
    assert "Example" in knowledge.examples("run a 10K")


# --- detailed-plan tests ------------------------------------------------------------------------------------
from app import planlint
from app.targets import facts


def test_outline_shape():
    rows = planlint.outline(P(weeks=12, days_per_week=4, experience="beginner", goal="run a half marathon"))
    assert len(rows) == 12
    by = {r["week"]: r for r in rows}
    assert by[4]["deload"] and by[4]["minutes"] < by[3]["minutes"]
    assert by[12]["taper"] and by[12]["minutes"] < by[11]["minutes"] < by[10]["minutes"]
    builds = [r["minutes"] for r in rows if not r["deload"] and not r["taper"]]
    assert all(b2 / b1 <= 1.12 for b1, b2 in zip(builds, builds[1:]))  # <= ~10% rounding included


def test_outline_minor_growth_capped():
    rows = planlint.outline(P(age=15, weeks=12, goal="run a 5k"))
    builds = [r["minutes"] for r in rows if not r["deload"] and not r["taper"]]
    assert all(b2 / b1 <= 1.10 for b1, b2 in zip(builds, builds[1:]))


def test_lint_catches_errors():
    p = P(days_per_week=4)
    row = dict(week=1, phase="Base", minutes=100, deload=False, taper=False)
    bad = {"week": 1, "sessions": [{"day": "Mon", "type": "long", "minutes": 100, "effort": "x", "details": ["y"]}]}
    msgs = [m for sev, m in planlint.lint_week(bad, row, p) if sev == "error"]
    assert any("expected exactly 4" in m for m in msgs)
    assert any("longest session" in m for m in msgs)


def test_pipeline_builds_detailed_weeks_and_regenerates_flagged_block():
    llm = MockLLM()

    async def go():
        return [e async for e in run_pipeline(P(weeks=8, days_per_week=4, experience="beginner"), llm)]
    evs = asyncio.run(go())
    final = evs[-1]["markdown"]
    assert "## Week-by-week plan" in final and "### Week 1" in final and "### Week 8" in final
    assert "{{WEEKLY_PLAN}}" not in final
    assert evs[[e["stage"] for e in evs].index("research") + 0]["stage"] == "research"
    done = [e for e in evs if e["stage"] == "research" and e["status"] == "done"][0]["data"]
    assert done["automated_errors"] == 0
    # 8 weeks = 2 blocks; critic flagged Week 2 -> block 1 rebuilt once more (3 block calls total)
    assert llm.calls.count("block") == 3


def test_facts_minor_has_no_numbers():
    s = screen(P(age=15))
    f = facts(P(age=15, weight_kg=55), s)
    assert "g/kg" not in f and "NO calorie counts" in f
    assert "g/kg" in facts(P(weight_kg=70), screen(P()))


# --- malformed model output ---------------------------------------------------------------------------------
def test_lenient_json_parsing():
    rows = [dict(week=1, phase="Base", minutes=100, deload=False, taper=False)]
    good = '{"weeks": [{"week": 1, "sessions": [{"day": "Mon", "type": "easy", "minutes": 30,},]},]}'
    fenced = "Here you go:\n```json\n" + good + "\n```"
    assert planlint.parse_block(fenced, rows)[0]["week"] == 1
    for bad in ('{"weeks": [{"week": 1, "sessions": [{"day": "Mon", "title": "Say "easy" now"}]}]}', "no json here"):
        try:
            planlint.parse_block(bad, rows)
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_block_uses_tool_and_recovers_from_bad_json():
    seen = {"tool": 0, "bad": 0}

    class Flaky(MockLLM):
        async def complete(self, role, system, user, max_tokens=0, tool=None):
            if role == "block":
                seen["tool"] += 1 if tool and tool["name"] == "submit_weeks" else 0
                if seen["bad"] < 2:
                    seen["bad"] += 1
                    return '{"weeks": [{"week": 1, "sessions": [{"day": "Mon", "title": "Say "easy" now"}'
            return await super().complete(role, system, user, max_tokens, tool)

    async def go():
        return [e async for e in run_pipeline(P(weeks=4, days_per_week=3, experience="beginner"), Flaky())]
    evs = asyncio.run(go())
    assert evs[-1]["stage"] == "final" and "### Week 4" in evs[-1]["markdown"]
    assert seen["tool"] >= 3 and seen["bad"] == 2


def test_block_tool_schema_is_json():
    json.dumps(planlint.BLOCK_TOOL)
    assert planlint.BLOCK_TOOL["input_schema"]["required"] == ["weeks"]


def test_anthropic_wrapper_does_not_force_tool_choice_and_has_text_fallback():
    import asyncio as aio
    from types import SimpleNamespace as NS
    from app.llm import AnthropicLLM
    calls = []

    def make(content):
        async def create(**kw):
            calls.append(kw)
            return NS(content=content)
        return NS(messages=NS(create=create))

    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.web_search = False
    tool = planlint.BLOCK_TOOL
    llm.client = make([NS(type="text", text="Sure!"), NS(type="tool_use", name="submit_weeks", input={"weeks": [{"week": 1}]})])
    out = aio.run(llm.complete("block", "SYS", "USER", 100, tool=tool))
    assert json.loads(out) == {"weeks": [{"week": 1}]}
    assert "tool_choice" not in calls[-1] and "submit_weeks" in calls[-1]["system"] and calls[-1]["tools"] == [tool]
    llm.client = make([NS(type="text", text='{"weeks": []}')])   # model answered in text instead of calling the tool
    assert aio.run(llm.complete("block", "SYS", "USER", 100, tool=tool)) == '{"weeks": []}'
    llm.client = make([NS(type="text", text="hello")])
    assert aio.run(llm.complete("editor", "SYS", "USER", 100)) == "hello" and "tools" not in calls[-1]


# --- two-layer safety -----------------------------------------------------------------------------------------
def test_screen_with_model_second_layer():
    from app.safety import screen_with_model

    class FakeLLM:
        classifies_safety = True

        def __init__(self, flags):
            self.flags, self.called = flags, 0

        async def complete(self, role, system, user, max_tokens=0, tool=None):
            self.called += 1
            assert role == "safety" and tool["name"] == "report_red_flags" and "<user_text>" in user
            return json.dumps({"red_flags": self.flags})

    p = P(notes="I feel short of breath on stairs and my ankles swell")
    assert screen(p).level != "hold"                         # keyword layer misses it
    llm = FakeLLM([{"label": "breathlessness with ankle swelling", "category": "cardiac"}])
    s = asyncio.run(screen_with_model(p, llm))
    assert s.level == "hold" and "doctor" in s.message and llm.called == 1
    crisis = asyncio.run(screen_with_model(P(notes="rough week"), FakeLLM([{"label": "x", "category": "crisis"}])))
    assert "Samaritans" in crisis.message
    clean = FakeLLM([])
    assert asyncio.run(screen_with_model(P(notes="calves tight after leg day"), clean)).level == "ok"
    kw = FakeLLM([])
    assert asyncio.run(screen_with_model(P(notes="chest pain on runs"), kw)).level == "hold" and kw.called == 0   # keyword hold short-circuits
    assert asyncio.run(screen_with_model(P(notes="x"), MockLLM())).level == "ok"          # mock never calls the classifier


def test_keyword_patterns_avoid_gym_slang_false_alarms():
    for ok_note in ("chest day is my favourite", "calves feel tight after leg day", "8000 steps a day", "my physio cleared my knee"):
        assert screen(P(notes=ok_note)).level != "hold", ok_note
    for bad in ("tightness in my chest", "I went lightheaded", "eating 900 a day", "want to try SARMs", "I want to end my life"):
        assert screen(P(notes=bad)).level == "hold", bad
