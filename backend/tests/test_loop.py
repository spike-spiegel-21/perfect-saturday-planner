"""The execution loop with a scripted model: happy path, every guard, and every fallback path."""

import json

from app.agent.loop import run_agent
from app.config import Limits
from app.data import load_city
from app.llm import LLMError
from tests.fakes import FakeLLM, plan_step, prefs, text_step, tool_step

P = prefs()
SEARCH = tool_step(
    ("get_weather", {"city": "Bangalore"}),
    ("search_events", {"categories": ["music", "walk", "nature", "food_walk"], "max_price": 1000}),
    ("search_restaurants", {"max_cost_for_one": 800}),
    text="Checking Saturday's weather, events and veg-friendly food in parallel.",
)


async def run(llm, **kw):
    events = []

    async def emit(e):
        events.append(e)

    result = await run_agent(kw.pop("p", P), load_city("bangalore"), llm, emit, run_id="r1", limits=kw.pop("limits", Limits()), **kw)
    return result, events


def types(events):
    return [e["type"] for e in events]


async def test_happy_path_submits_three_validated_options():
    llm = FakeLLM([SEARCH, plan_step("validate_plan", P), plan_step("submit_plans", P)])
    result, events = await run(llm)
    run_ = result.run
    assert not run_.fallback and [o.kind for o in run_.options] == ["time_saver", "recommended", "value_for_money"]
    assert all(o.source == "agent" and o.validation.status != "fail" for o in run_.options)
    assert run_.usage["steps"] == 3 and run_.usage["tool_calls"] == 5
    assert run_.usage["cost_usd"] > 0
    names = [e["name"] for e in events if e["type"] == "tool_call"]
    assert names == ["get_weather", "search_events", "search_restaurants", "validate_plan", "submit_plans"]
    assert "narration" in types(events) and types(events)[-1] == "plans"
    assert sum(1 for e in events if e["type"] == "validation") == 6  # 3 on validate, 3 on submit
    # the model saw real tool results, and reasoning-preserving assistant messages were replayed verbatim
    history = llm.calls[-1][0]
    assert history[0]["role"] == "system" and any(m["role"] == "tool" for m in history)
    assert result.trace == events


async def test_repeating_the_same_call_ends_in_fallback():
    loop_forever = FakeLLM([tool_step(("get_weather", {"city": "Bangalore"}))], repeat_last=True)
    result, events = await run(loop_forever)
    run_ = result.run
    assert run_.fallback and run_.fallback_reason == "the agent hit its step limit"
    assert run_.usage["steps"] == Limits().max_steps
    assert len(run_.options) == 3 and all(o.source == "fallback" for o in run_.options)
    cached = [e for e in events if e["type"] == "tool_result" and e["cached"]]
    assert len(cached) == Limits().max_steps - 1
    assert {"guard", "fallback"} <= set(types(events))


TWELVE_LEGS = tool_step(*[
    ("get_travel", {"legs": [{"from_id": "start", "to_id": "start", "depart": f"{h:02d}:00"}]}) for h in range(8, 20)
])


async def test_tool_budget_guard():
    result, _ = await run(FakeLLM([TWELVE_LEGS]), limits=Limits(max_tool_calls=10, caps={"get_travel": 100}))
    assert result.run.fallback_reason == "the agent hit its tool-call limit"
    assert result.run.usage["tool_calls"] == 12


async def test_per_tool_cap_guard():
    result, events = await run(FakeLLM([TWELVE_LEGS, LLMError("stop")]))
    capped = [e for e in events if e["type"] == "tool_result" and not e["ok"] and "limit reached" in e["summary"]]
    assert len(capped) == 12 - Limits().caps["get_travel"]
    assert any(e["type"] == "guard" and e["name"] == "tool_cap" for e in events)
    assert result.run.usage["tool_calls"] == Limits().caps["get_travel"]


async def test_three_rejected_submissions_fall_back():
    bad = {"options": [
        {"kind": k, "title": "x", "pitch": "y", "items": [{"ref_id": "ban_imaginary", "start": "16:00", "why_it_fits": "trust me, it fits"}]}
        for k in ("time_saver", "recommended", "value_for_money")
    ]}
    llm = FakeLLM([SEARCH] + [tool_step(("submit_plans", bad))] * 3)
    result, events = await run(llm)
    assert result.run.fallback_reason == "the agent's plans kept failing validation"
    rejected = [e for e in events if e["type"] == "tool_result" and e["name"] == "submit_plans"]
    assert len(rejected) == 3 and all("rejected" in e["summary"] for e in rejected)


async def test_partial_submission_is_kept_and_gaps_filled():
    def half_good(messages, kwargs):
        step = plan_step("submit_plans", P)(messages, kwargs)
        args = json.loads(step.tool_calls[0].arguments)
        args["options"][2]["items"][0]["ref_id"] = "ban_imaginary"  # break value_for_money only
        step.tool_calls[0].arguments = json.dumps(args)
        return step

    llm = FakeLLM([SEARCH, half_good, LLMError("boom", "unavailable")])
    result, events = await run(llm)
    sources = {o.kind: o.source for o in result.run.options}
    assert sources == {"time_saver": "agent", "recommended": "agent", "value_for_money": "fallback"}
    fb = next(e for e in events if e["type"] == "fallback")
    assert fb["kept_from_agent"] == ["recommended", "time_saver"] and fb["filled"] == ["value_for_money"]


async def test_llm_down_uses_rule_based_plans():
    result, events = await run(FakeLLM([LLMError("402 out of credits", "credits")]))
    assert result.run.fallback and "unavailable" in result.run.fallback_reason
    assert len(result.run.options) == 3
    assert next(e for e in events if e["type"] == "fallback")["detail"].endswith("(402 out of credits)")


async def test_simulated_llm_outage_never_calls_the_model():
    llm = FakeLLM([])
    result, _ = await run(llm, simulate=frozenset({"llm_down"}))
    assert result.run.fallback and llm.calls == []


async def test_text_only_answers_get_one_nudge():
    llm = FakeLLM([text_step("Here's a lovely plan for you!"), text_step("As I said, go to the park.")])
    result, events = await run(llm)
    assert result.run.fallback_reason == "the agent stopped without submitting plans"
    assert any(e["type"] == "guard" and e["name"] == "nudge" for e in events)
    assert llm.calls[1][0][-1]["role"] == "user"  # the nudge was appended, the system prompt untouched


async def test_weather_outage_reaches_the_model_as_a_tool_error():
    llm = FakeLLM([SEARCH, plan_step("submit_plans", P)])
    result, events = await run(llm, simulate=frozenset({"weather_down"}))
    weather = next(e for e in events if e["type"] == "tool_result" and e["name"] == "get_weather")
    assert not weather["ok"] and "unavailable" in weather["error"]
    assert "unavailable" in result.run.weather_note
    tool_msgs = [m for m in llm.calls[1][0] if m["role"] == "tool"]
    assert "unavailable" in tool_msgs[0]["content"]


async def test_run_assumptions_include_intake_defaults():
    result, _ = await run(FakeLLM([LLMError("x")]), extra_assumptions=["You didn't pin down a budget, so I assumed ₹1,500."])
    assert result.run.assumptions[0].startswith("You didn't pin down a budget")
    assert any("start time" in a for a in result.run.assumptions)


async def test_wrap_up_warning_two_turns_before_the_cap():
    loop_forever = FakeLLM([tool_step(("get_weather", {"city": "Bangalore"}))], repeat_last=True)
    _, events = await run(loop_forever)
    wrap_at = [i for i, e in enumerate(events) if e["type"] == "guard" and e["name"] == "wrap_up"]
    assert len(wrap_at) == 1
    steps_before = [e["n"] for e in events[: wrap_at[0]] if e["type"] == "step"]
    assert steps_before[-1] == Limits().max_steps - 2
