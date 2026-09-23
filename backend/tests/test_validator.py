import pytest

from app.agent.fallback import build_fallback
from app.models import PlanItemIn, PlanOptionIn, PlanOptionOut
from app.tools.validate import SubmitArgs, evaluate, submit_plans
from app.tools.weather import hour_weather, is_bad
from app.util import fmt, to_min
from tests.fakes import ctx_for, prefs


def as_in(out: PlanOptionOut, **overrides) -> PlanOptionIn:
    data = {
        "kind": out.kind, "title": out.title, "pitch": out.pitch, "tradeoffs": list(out.tradeoffs),
        "items": [PlanItemIn(ref_id=i.ref_id, start=i.start, duration_min=i.duration_min, why_it_fits=i.why_it_fits)
                  for i in out.items],
    }
    data.update(overrides)
    return PlanOptionIn(**data)


def item(place, start: str, why: str = "Fits your mood and interests nicely.", **kw) -> PlanItemIn:
    return PlanItemIn(ref_id=place.id, start=start, why_it_fits=why, **kw)


@pytest.fixture
def ctx():
    c = ctx_for(prefs(budget_inr=3000, start_time="12:00", available_hours=9, rules={"vegetarian": True}))
    c.seen_ids.update(c.places)  # most tests are about rules, not grounding
    return c


def test_fallback_options_validate(ctx):
    built = build_fallback(ctx)
    assert set(built) == {"time_saver", "recommended", "value_for_money"}
    for out in built.values():
        again = evaluate(ctx, as_in(out))
        assert again.validation.status != "fail", again.validation.violations
        assert again.totals.cost_inr == out.totals.cost_inr
        assert again.totals.cost_inr == again.totals.spend_inr + again.totals.travel_inr


def test_unknown_and_ungrounded_ids(ctx):
    place = ctx.city.places[0]
    ctx.seen_ids.discard(place.id)
    out = evaluate(ctx, PlanOptionIn(kind="recommended", title="t", pitch="p", items=[
        PlanItemIn(ref_id="ban_made_up_place", start="13:00", why_it_fits="Sounds lovely for you."),
        item(place, "13:00"),
    ]))
    text = " ".join(out.validation.violations)
    assert "unknown place id" in text and "was not returned by a search" in text


def test_event_times_snap_to_the_next_reachable_showtime(ctx):
    event = next(p for p in ctx.city.places if p.kind == "event" and len(p.start_times) >= 2
                 and to_min(p.start_times[0]) >= ctx.window_start + 60)
    first = to_min(event.start_times[0])
    out = evaluate(ctx, PlanOptionIn(kind="recommended", title="t", pitch="p", items=[item(event, fmt(first + 10))]))
    assert out.items[0].start in event.start_times and to_min(out.items[0].start) > first
    assert out.validation.adjusted and not any("showtime" in v for v in out.validation.violations)


def test_unreachable_showtime_is_a_violation(ctx):
    event = next(p for p in ctx.city.places if p.kind == "event")
    last = max(to_min(t) for t in event.start_times)
    out = evaluate(ctx, PlanOptionIn(kind="recommended", title="t", pitch="p", items=[item(event, fmt(last + 30))]))
    assert any("no showtime" in v for v in out.validation.violations)


def test_restaurant_must_be_open(ctx):
    rest = next(p for p in ctx.city.places if p.kind == "restaurant" and p.veg != "non_veg")
    closes = max(to_min(c) for _, c in rest.open_hours)
    out = evaluate(ctx, PlanOptionIn(kind="recommended", title="t", pitch="p",
                                     items=[item(rest, fmt(closes - 10), duration_min=45)]))
    assert any("is open" in v for v in out.validation.violations)


def test_travel_time_between_stops_is_respected(ctx):
    acts = [p for p in ctx.city.places if p.kind == "activity" and any(to_min(o) <= 13 * 60 for o, _ in p.open_hours)]
    a, b = max(((x, y) for x in acts for y in acts if x.id != y.id),
               key=lambda xy: abs(xy[0].lat - xy[1].lat) + abs(xy[0].lng - xy[1].lng))
    end_a = 13 * 60 + a.typical_min
    out = evaluate(ctx, PlanOptionIn(kind="recommended", title="t", pitch="p",
                                     items=[item(a, "13:00"), item(b, fmt(end_a))]))
    second = out.items[1]
    assert to_min(second.start) >= to_min(out.items[0].end) + second.leg_before.minutes
    assert any(b.name in adj for adj in out.validation.adjusted)


def test_budget_thresholds(ctx):
    base = build_fallback(ctx)["recommended"]
    cost = base.totals.cost_inr
    assert cost > 0
    ctx.prefs.budget_inr = int(cost / 1.05)  # ~5% over
    stretched = as_in(base, tradeoffs=["About ₹100 over budget, but it fits your mood better."])
    assert evaluate(ctx, stretched).validation.status == "warn"
    assert any("over the" in v for v in evaluate(ctx, as_in(base, tradeoffs=[])).validation.violations)
    assert evaluate(ctx, as_in(base, kind="time_saver", tradeoffs=stretched.tradeoffs)).validation.status == "fail"
    ctx.prefs.budget_inr = int(cost / 1.3)
    assert evaluate(ctx, stretched).validation.status == "fail"


def test_vegetarian_rule(ctx):
    meat = next((p for p in ctx.city.places if p.kind == "restaurant" and p.veg == "non_veg"), None)
    if meat is None:
        pytest.skip("no non-veg restaurant in data")
    o, _ = meat.open_hours[0]
    out = evaluate(ctx, PlanOptionIn(kind="recommended", title="t", pitch="p", items=[item(meat, o)]))
    assert any("not vegetarian" in v for v in out.validation.violations)


def test_avoid_crowds_rule():
    c = ctx_for(prefs(start_time="17:00", available_hours=4, rules={"avoid_crowds": True}))
    c.seen_ids.update(c.places)
    busy = next(p for p in c.city.places if p.kind == "activity" and p.crowd.evening == "high"
                and any(to_min(o) <= 17 * 60 + 30 and to_min(cl) >= 18 * 60 + 30 for o, cl in p.open_hours))
    out = evaluate(c, PlanOptionIn(kind="recommended", title="t", pitch="p", items=[item(busy, "17:30", duration_min=45)]))
    assert any("crowded" in v for v in out.validation.violations)


def test_outdoor_in_bad_weather_needs_a_tradeoff():
    for city in ("bangalore", "mumbai", "gurgaon", "delhi"):
        c = ctx_for(prefs(city=city, city_name=city.title(), start_time="08:00", available_hours=15.5, rules={}))
        c.seen_ids.update(c.places)
        for p in c.city.places:
            if p.indoor or p.kind != "activity":
                continue
            for o, cl in p.open_hours:
                for m in range(to_min(o), to_min(cl) - 30, 30):
                    h = hour_weather(c.city, m)
                    if h and is_bad(h):
                        opt = PlanOptionIn(kind="recommended", title="t", pitch="p", items=[item(p, fmt(m), duration_min=30)])
                        out = evaluate(c, opt)
                        assert any("outdoors" in v for v in out.validation.violations)
                        opt.tradeoffs = ["Could rain then, so carry an umbrella."]
                        assert not any("outdoors" in v for v in evaluate(c, opt).validation.violations)
                        return
    pytest.skip("no outdoor activity overlaps bad weather in the data")


def test_back_by_rule(ctx):
    ctx.prefs.rules.end_by = "14:00"
    out = build_fallback(ctx)["recommended"]
    res = evaluate(ctx, as_in(out))
    if to_min(res.totals.end) > 14 * 60:
        assert any("after your 14:00 limit" in v for v in res.validation.violations)


async def test_submit_rejects_bad_sets_and_accepts_good(ctx):
    built = build_fallback(ctx)
    good = [as_in(built[k]) for k in ("time_saver", "recommended", "value_for_money")]
    res = await submit_plans(ctx, SubmitArgs(options=[good[0], good[1], good[1]]))
    assert res["status"] == "rejected" and "exactly one each" in str(res["problems"])

    same = [good[0], as_in(built["time_saver"], kind="recommended"), good[2]]
    res = await submit_plans(ctx, SubmitArgs(options=same))
    assert res["status"] == "rejected" and "same stops" in str(res["problems"])
    assert not ctx.accepted

    res = await submit_plans(ctx, SubmitArgs(options=good))
    assert res["status"] == "accepted" and ctx.accepted
    assert set(ctx.best) == {"time_saver", "recommended", "value_for_money"}


def test_thin_plans_must_fill_the_window_or_explain(ctx):
    cafe = next(p for p in ctx.city.places if p.kind == "restaurant" and p.veg != "non_veg"
                and any(to_min(o) <= 13 * 60 and to_min(c) >= 14 * 60 for o, c in p.open_hours))
    thin = PlanOptionIn(kind="recommended", title="t", pitch="p", items=[item(cafe, "13:00", duration_min=45)])
    assert any("min at stops" in v for v in evaluate(ctx, thin).validation.violations)
    thin.tradeoffs = ["Keeping it short and light because it's raining all afternoon."]
    out = evaluate(ctx, thin)
    assert not any("min at stops" in v for v in out.validation.violations)
    assert any("min at stops" in w for w in out.validation.warnings)
