"""Conversational intake: extraction, question order, pills, vague answers, failures and refinement."""

import pytest

from app.intake import (
    FIELDS, ORDER, TurnState, default_start, handle_turn, merge, regex_extract, rules_from, to_preferences,
)
from app.llm import DisabledLLM, LLMError
from app.models import Slots
from tests.fakes import FakeLLM, extraction, json_step

NO_LLM = DisabledLLM()


async def converse(llm, texts, status="collecting", profile=None):
    slots, state, turns = Slots(), TurnState(), []
    for text in texts:
        res = await handle_turn(llm, text, slots, state, status=status, profile=profile)
        slots, state = res.slots, res.state
        turns.append(res.turn)
    return turns, slots, state


# ---------------------------------------------------------------- regex fallback


@pytest.mark.parametrize("text,asking,expect", [
    ("i am at the gurgaon, and my budget is ₹3000", None, {"city": "Gurgaon", "budget_inr": 3000}),
    ("Bengaluru, 2k budget", None, {"city": "Bangalore", "budget_inr": 2000}),
    ("rs 1,500", None, {"budget_inr": 1500}),
    ("2500", "budget", {"budget_inr": 2500}),
    ("4 hours", "available_time", {"available_hours": 4}),
    ("3", "available_time", {"available_hours": 3}),
    ("3pm to 9pm", "available_time", {"available_hours": 6, "start_time": "15:00"}),
    ("half day", "available_time", {"available_hours": 6}),
    ("free after 5pm", None, {"start_time": "17:00", "available_hours": 5}),
    ("tired but want some fun", "mood", {"mood": "tired but want some fun", "energy": "low"}),
    ("food, live music and walks", "interests", {"interests": ["food", "live music", "walks"]}),
    ("none", "constraints", {"constraints": []}),
    ("vegetarian, avoid crowds", "constraints", {"constraints": ["vegetarian", "avoid crowds"]}),
])
def test_regex_extract(text, asking, expect):
    ex = regex_extract(text, asking)
    for k, v in expect.items():
        assert getattr(ex, k) == v, (k, getattr(ex, k))


def test_budget_numbers_are_not_clock_times():
    ex = regex_extract("budget ₹2000-3000", None)
    assert ex.available_hours is None and ex.start_time is None


def test_rules_from_constraints():
    r = rules_from(["vegetarian", "avoid crowds", "back by 9pm", "no alcohol"])
    assert r.vegetarian and r.avoid_crowds and r.no_alcohol and r.end_by == "21:00"
    assert not rules_from(["non-veg is fine"]).vegetarian
    assert rules_from(["jain"]).vegetarian and rules_from(["wheelchair access"]).wheelchair


# ---------------------------------------------------------------- the conversation


async def test_full_flow_without_llm_asks_in_order():
    turns, slots, _ = await converse(NO_LLM, [
        "i am at the gurgaon, and my budget is ₹3000",
        "4 hours",
        "tired but want to do something fun",
        "food, music",
        "vegetarian, avoid crowded places",
    ])
    assert [t.asking for t in turns] == ["available_time", "mood", "interests", "constraints", None]
    assert [t.ready for t in turns] == [False, False, False, False, True]
    assert turns[0].pills and turns[0].placeholder == FIELDS["available_time"].placeholder
    assert turns[1].multi and turns[2].multi
    assert slots.city == "gurgaon" and slots.budget_inr == 3000 and slots.rules.vegetarian and slots.rules.avoid_crowds
    assert all(t.parse["method"] == "rules" for t in turns)


async def test_first_answer_can_fill_everything_at_once():
    llm = FakeLLM([json_step(extraction(
        city="Bangalore", budget_inr=2000, available_hours=4, mood="tired but wants to do something fun", energy="low",
        interests=["food", "music", "walks"], constraints=["vegetarian", "avoid crowds"], ack="A slow, veg-friendly Saturday, got it.",
    ))])
    turns, slots, _ = await converse(llm, ["Bangalore, ₹2000, 4 hours, tired, food/music/walks, veg, no crowds"])
    assert turns[0].ready and turns[0].reply.startswith("A slow, veg-friendly Saturday")
    prefs = to_preferences(slots)
    assert prefs.start_time == "16:00" and prefs.start_time_assumed


async def test_unsupported_city_is_handled_before_anything_runs():
    llm = FakeLLM([json_step(extraction(city="Jaipur", budget_inr=1000))])
    turns, slots, _ = await converse(llm, ["I'm in Jaipur with 1000"])
    t = turns[0]
    assert "don't have data for Jaipur" in t.reply and t.asking == "city" and not t.ready
    assert [p.value for p in t.pills] == ["Bangalore", "Gurgaon", "Delhi", "Mumbai"]
    assert slots.city is None and slots.budget_inr == 1000


async def test_vague_budget_gets_clarified_then_defaulted():
    vague = json_step(extraction(vague_fields=["budget"], ack="No worries."))
    llm = FakeLLM([json_step(extraction(city="Mumbai", ack="Mumbai, lovely.")), vague, vague, vague])
    turns, slots, state = await converse(llm, ["mumbai", "not too much", "cheap-ish", "idk"])
    assert turns[0].asking == "budget" and turns[0].reply.endswith(FIELDS["budget"].question)
    assert turns[1].reply.endswith(FIELDS["budget"].reask)
    assert turns[3].asking == "available_time"
    assert slots.budget_inr == 1500 and any("assumed ₹1,500" in a for a in state.assumed)


async def test_constraints_none_and_mood_before_interests():
    turns, slots, _ = await converse(NO_LLM, ["delhi, ₹1500, 3 hours", "chill", "movies", "none"])
    assert [t.asking for t in turns[:3]] == ["mood", "interests", "constraints"]
    assert turns[-1].ready and slots.constraints == []


async def test_llm_failure_mid_conversation_falls_back_to_rules():
    llm = FakeLLM([json_step(extraction(city="Delhi", ack="Delhi it is.")), LLMError("down")])
    turns, slots, _ = await converse(llm, ["Delhi", "₹2000"])
    assert turns[0].parse["method"] == "llm" and turns[1].parse["method"] == "rules"
    assert slots.budget_inr == 2000


async def test_memory_pills_come_first_but_never_autofill():
    profile = {"home_city_name": "Gurgaon", "last_budget": 3000, "constraints": ["vegetarian"], "interest_counts": {"food": 2}}
    turns, slots, _ = await converse(NO_LLM, ["hello"], profile=profile)
    city_pills = turns[0].pills
    assert city_pills[0].remembered and city_pills[0].value == "Gurgaon" and "(last time)" in city_pills[0].label
    assert slots.city is None


async def test_post_plan_refinement_triggers_replan():
    slots = Slots(city="gurgaon", city_name="Gurgaon", budget_inr=3000, available_hours=4, mood="tired", interests=["food"], constraints=[])
    llm = FakeLLM([json_step(extraction(refinement_note="make it cheaper", ack="Sure, cheaper it is."))])
    res = await handle_turn(llm, "make it cheaper", slots, TurnState(), status="planned", profile=None)
    assert res.replan and res.turn.ready and res.state.refinement == "make it cheaper"

    llm = FakeLLM([json_step(extraction(ack="Glad you like it!"))])
    res = await handle_turn(llm, "thanks!", slots, TurnState(), status="planned", profile=None)
    assert not res.replan and not res.turn.ready and res.turn.pills


def test_merge_unions_lists_and_recomputes_rules():
    s = Slots(interests=["food"], constraints=["vegetarian"])
    m = merge(s, regex_extract("avoid crowds", "constraints"), "constraints")
    assert m.slots.constraints == ["vegetarian", "avoid crowds"] and m.slots.rules.avoid_crowds
    m = merge(s, regex_extract("music and walks", "interests"), "interests")
    assert m.slots.interests == ["food", "music", "walks"]


def test_default_start_times():
    assert default_start(4, None) == "16:00"
    assert default_start(10, None) == "10:00"
    assert default_start(6, None) == "14:00"
    assert default_start(4, "20:00") == "16:00"
    assert default_start(4, "18:00") == "14:00"
    assert ORDER.index("mood") < ORDER.index("interests") < ORDER.index("constraints")


async def test_refinement_pills_work_without_the_model():
    slots = Slots(city="gurgaon", city_name="Gurgaon", budget_inr=3000, available_hours=4, mood="tired", interests=["food"], constraints=[])
    res = await handle_turn(NO_LLM, "Make it cheaper, Less travel", slots, TurnState(), status="planned", profile=None)
    assert res.replan and "cheaper" in res.state.refinement
