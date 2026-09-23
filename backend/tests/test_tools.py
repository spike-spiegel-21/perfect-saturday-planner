import json

import pytest

from app.config import Limits
from app.llm import ToolCall
from app.tools import build_tools
from app.tools.events import EventsArgs, search_events
from app.tools.places import crowd_in_window
from app.tools.registry import dispatch, inline_schema
from app.tools.restaurants import RestaurantArgs, search_restaurants
from app.tools.travel import TravelArgs, get_travel, mode_options
from app.tools.weather import WeatherArgs, get_weather
from app.util import to_min
from tests.fakes import ctx_for, prefs

TOOLS = build_tools()


def test_tool_specs_are_self_contained():
    for tool in TOOLS.values():
        spec = tool.spec()
        text = json.dumps(spec)
        assert "$ref" not in text and "$defs" not in text
        assert spec["function"]["parameters"]["type"] == "object"
    assert set(TOOLS) == {"get_weather", "search_events", "search_restaurants", "get_travel", "validate_plan", "submit_plans"}
    assert inline_schema(EventsArgs)["properties"]["categories"]["items"]["enum"]


async def test_weather_is_limited_to_window():
    ctx = ctx_for(prefs())
    out = await get_weather(ctx, WeatherArgs(city="Bangalore"))
    hours = [int(h["time"][:2]) for h in out["in_your_window"]]
    assert hours[0] == 16 and hours[-1] == 20
    assert ctx.weather_summary


async def test_events_respect_window_price_and_mark_seen():
    ctx = ctx_for(prefs())
    out = await search_events(ctx, EventsArgs(categories=["music", "walk", "nature"], max_price=1000))
    assert 1 <= out["count"] <= 6
    for r in out["results"]:
        assert r["price_inr"] <= 1000
        assert r["id"] in ctx.seen_ids
        place = ctx.places[r["id"]]
        if place.kind == "event":
            assert all(to_min(t) >= ctx.window_start for t in r["start_times"])
        for alt in r.get("cheaper_alternatives", []):
            assert alt["price_inr"] < place.base_price and alt["id"] in ctx.seen_ids


async def test_restaurants_drop_non_veg_for_vegetarians():
    ctx = ctx_for(prefs())
    out = await search_restaurants(ctx, RestaurantArgs(max_cost_for_one=800))
    assert out["count"] >= 1
    assert all(r["veg"] != "non_veg" and r["cost_for_one"] <= 800 for r in out["results"])
    assert "not vegetarian" in out["hidden"]


async def test_wheelchair_rule_filters_events():
    p = prefs(constraints=["wheelchair access"], rules={"wheelchair": True})
    ctx = ctx_for(p)
    out = await search_events(ctx, EventsArgs())
    assert all("wheelchair_accessible" in r["tags"] for r in out["results"])


async def test_simulated_empty_restaurants():
    ctx = ctx_for(prefs(), simulate=frozenset({"no_restaurants"}))
    out = await search_restaurants(ctx, RestaurantArgs())
    assert out["count"] == 0 and "simulated" in out["note"]


async def test_travel_modes_and_policies():
    ctx = ctx_for(prefs())
    a, b = ctx.city.places[0], ctx.city.places[-1]
    km, opts = mode_options(ctx.city, a, b, 18 * 60)
    modes = {o.mode for o in opts}
    assert {"auto", "cab"} <= modes
    assert ("walk" in modes) == (km <= 2.0)
    out = await get_travel(ctx, TravelArgs(legs=[{"from_id": "start", "to_id": a.id}, {"from_id": a.id, "to_id": "nope"}]))
    assert out["legs"][0]["km"] > 0 and out["legs"][1]["error"]


async def test_evening_cabs_cost_more_than_afternoon():
    ctx = ctx_for(prefs())
    a, b = ctx.city.places[0], ctx.city.places[-1]
    _, day = mode_options(ctx.city, a, b, 14 * 60)
    _, eve = mode_options(ctx.city, a, b, 18 * 60)
    cab = lambda opts: next(o for o in opts if o.mode == "cab")  # noqa: E731
    assert cab(eve).fare_inr >= cab(day).fare_inr and cab(eve).minutes >= cab(day).minutes


def test_crowd_in_window_uses_slots():
    ctx = ctx_for(prefs(start_time="12:00", available_hours=8))
    park = next(p for p in ctx.city.places if p.kind == "activity")
    assert set(crowd_in_window(park, ctx.window_start, ctx.window_end)) == {"afternoon", "evening"}


# ---------------------------------------------------------------- dispatcher guards


async def _run(ctx, name, args):
    return await dispatch(ctx, TOOLS, ToolCall("c1", name, json.dumps(args) if isinstance(args, dict) else args))


async def test_dispatch_bad_json_and_unknown_tool():
    ctx = ctx_for(prefs())
    assert "invalid arguments JSON" in (await _run(ctx, "get_weather", "{nope"))["error"]
    assert "unknown tool" in (await _run(ctx, "book_table", {}))["error"]
    assert "invalid arguments" in (await _run(ctx, "get_travel", {"legs": []}))["error"]


async def test_dispatch_dedupes_identical_calls():
    events = []

    async def emit(e):
        events.append(e)

    ctx = ctx_for(prefs(), emit=emit)
    first = await _run(ctx, "get_weather", {"city": "Bangalore"})
    second = await _run(ctx, "get_weather", {"city": "Bangalore"})
    assert "duplicate call" in second["note"] and second["in_your_window"] == first["in_your_window"]
    assert ctx.counts["get_weather"] == 1
    assert [e["cached"] for e in events if e["type"] == "tool_result"] == [False, True]


async def test_dispatch_caps_per_tool():
    ctx = ctx_for(prefs(), limits=Limits(caps={"get_weather": 1}))
    await _run(ctx, "get_weather", {"city": "a"})
    capped = await _run(ctx, "get_weather", {"city": "b"})
    assert "limit reached" in capped["error"]


async def test_weather_outage_becomes_structured_error():
    ctx = ctx_for(prefs(), simulate=frozenset({"weather_down"}))
    out = await _run(ctx, "get_weather", {"city": "Bangalore"})
    assert "unavailable" in out["error"] and out["hint"]


@pytest.mark.parametrize("city", ["bangalore", "gurgaon", "delhi", "mumbai"])
async def test_every_city_has_searchable_options(city):
    from app.data import load_city

    c = load_city(city)
    ctx = ctx_for(prefs(city=city, city_name=c.name))
    assert (await search_events(ctx, EventsArgs()))["count"] >= 3
    assert (await search_restaurants(ctx, RestaurantArgs()))["count"] >= 2
