"""Shared place logic for the search tools and the fallback planner: hard filters, fit, scoring, compact views."""

from __future__ import annotations

from app.models import Place, Rules, interest_categories, interest_restaurant_tags
from app.tools.travel import ROAD_FACTOR, leg
from app.tools.weather import hour_weather, is_bad
from app.util import fmt, haversine_km, slot_of, to_min

MOOD_TAGS = {
    "romantic": "romantic", "date": "romantic", "partner": "romantic",
    "social": "social", "friends": "social", "people": "social",
    "quiet": "quiet", "calm": "quiet", "peace": "quiet", "me-time": "quiet", "alone": "quiet",
    "chill": "low_effort", "relax": "low_effort", "tired": "low_effort", "lazy": "low_effort", "slow": "low_effort",
    "adventur": "active", "energetic": "active", "active": "active",
    "family": "family", "kids": "family",
}


def rule_violation(p: Place, rules: Rules) -> str | None:
    """Hard constraints that make a place unusable for this user (None = fine)."""
    if p.kind == "restaurant":
        if (rules.vegetarian or rules.vegan or rules.jain) and p.veg == "non_veg":
            return "not vegetarian"
        if rules.vegan and "vegan_options" not in p.tags:
            return "no vegan options"
        if rules.jain and "jain_options" not in p.tags:
            return "no jain options"
    if rules.no_alcohol and "bar" in p.tags:
        return "a bar (you asked for no alcohol)"
    if rules.wheelchair and "wheelchair_accessible" not in p.tags:
        return "not wheelchair accessible"
    return None


def min_visit(p: Place) -> int:
    return max(30, min(p.typical_min, 60))


def event_starts(p: Place, start: int, end: int) -> list[str]:
    return [t for t in p.start_times if to_min(t) >= start and to_min(t) + (p.duration_min or 60) <= end]


def open_spans(p: Place, start: int, end: int) -> list[tuple[int, int]]:
    """Parts of the opening hours inside the window that are long enough for a visit."""
    spans = []
    for o, c in p.open_hours:
        s, e = max(to_min(o), start), min(to_min(c), end)
        if e - s >= min_visit(p):
            spans.append((s, e))
    return spans


def fits_window(p: Place, start: int, end: int) -> bool:
    return bool(event_starts(p, start, end)) if p.kind == "event" else bool(open_spans(p, start, end))


# Travel-aware fit: what the model gets told, so it doesn't draft times the validator will reject.
TRAVEL_SLACK = 5    # same leniency as the validator
RETURN_GRACE = 15


def earliest_arrival(ctx, p: Place) -> int:
    """Soonest the user can be at `p` if they leave the start point when their window opens."""
    return ctx.window_start + leg(ctx.city, ctx.start_point, p, ctx.window_start, "recommended").minutes


def reachable_starts(ctx, p: Place) -> list[str]:
    """Event start times the user can make and still get back before the window closes."""
    arrive = earliest_arrival(ctx, p)
    out = []
    for t in event_starts(p, ctx.window_start, ctx.window_end):
        start, end = to_min(t), to_min(t) + (p.duration_min or 60)
        back = leg(ctx.city, p, ctx.start_point, end, "recommended").minutes
        if arrive <= start + TRAVEL_SLACK and end + back <= ctx.window_end + RETURN_GRACE:
            out.append(t)
    return out


def fits_with_travel(ctx, p: Place) -> bool:
    if p.kind == "event":
        return bool(reachable_starts(ctx, p))
    arrive = earliest_arrival(ctx, p)
    back = leg(ctx.city, p, ctx.start_point, ctx.window_end - 60, "recommended").minutes
    latest_end = ctx.window_end + RETURN_GRACE - back
    return any(min(to_min(c), latest_end) - max(to_min(o), arrive) >= min_visit(p) for o, c in p.open_hours)


def window_slots(start: int, end: int) -> list[str]:
    slots = []
    for m in range(start, max(start + 1, end), 30):
        s = slot_of(m)
        if s not in slots:
            slots.append(s)
    return slots


def crowd_in_window(p: Place, start: int, end: int) -> dict[str, str]:
    if p.kind == "event":
        slots = []
        for t in event_starts(p, start, end):
            s = slot_of(to_min(t))
            if s not in slots:
                slots.append(s)
    else:
        slots = window_slots(start, end)
    return {s: getattr(p.crowd, s) for s in slots}


def km_from(a_lat: float, a_lng: float, p: Place) -> float:
    return round(haversine_km(a_lat, a_lng, p.lat, p.lng) * ROAD_FACTOR, 1)


def score(ctx, p: Place) -> float:
    """How well a place suits this user. Used for ranking search results and by the fallback planner."""
    prefs = ctx.prefs
    s = 0.0
    tags = set(p.tags)
    joined = " ".join(prefs.interests).lower()
    if p.kind == "restaurant":
        if tags & interest_restaurant_tags(prefs.interests):
            s += 2
        if "food" in joined or "eat" in joined:
            s += 1
        if prefs.rules.vegetarian and p.veg == "pure_veg":
            s += 0.5
    elif p.category in interest_categories(prefs.interests) or "surprise" in joined:
        s += 3
    if prefs.energy == "low":
        s += 1.5 * bool(tags & {"low_effort", "seated"}) - 2 * ("active" in tags)
    elif prefs.energy == "high":
        s += 1.5 * ("active" in tags)
    mood = prefs.mood.lower()
    s += sum(1.0 for word, tag in MOOD_TAGS.items() if word in mood and tag in tags)
    levels = list(crowd_in_window(p, ctx.window_start, ctx.window_end).values())
    highs = levels.count("high")
    if prefs.rules.avoid_crowds:
        s -= 3 if levels and highs == len(levels) else 1.5 * bool(highs)
        s += 0.5 * (bool(levels) and all(v == "low" for v in levels))
    else:
        s -= 0.3 * highs
    if not p.indoor and "weather_down" not in ctx.simulate:
        hours = range(ctx.window_start, ctx.window_end, 60)
        bad = sum(1 for m in hours if (h := hour_weather(ctx.city, m)) and is_bad(h))
        s -= 2.0 * bad / max(1, len(hours))
    if p.id in ctx.past_place_ids:
        s -= 2
    s -= 0.08 * km_from(ctx.start_point.lat, ctx.start_point.lng, p)
    s += 0.3 * bool(tags & {"hidden_gem", "iconic"})
    return round(s, 2)


def _hours(p: Place) -> str:
    return ", ".join(f"{o}–{c}" for o, c in p.open_hours)


def compact(ctx, p: Place, *, with_alternatives: bool = True) -> dict:
    """What the model sees for one place: only the fields it needs to plan."""
    ctx.seen_ids.add(p.id)
    base: dict = {
        "id": p.id, "name": p.name, "area": p.area,
        "km_from_start": km_from(ctx.start_point.lat, ctx.start_point.lng, p),
        "earliest_arrival": fmt(earliest_arrival(ctx, p)),
    }
    if p.kind == "restaurant":
        base.update({
            "cuisine": p.cuisine, "open": _hours(p), "cost_for_one": p.cost_for_one, "veg": p.veg, "meal_min": p.meal_min,
        })
    else:
        base.update({"kind": p.kind, "category": p.category, "duration_min": p.duration_min})
        if p.kind == "event":
            base["start_times"] = reachable_starts(ctx, p) or event_starts(p, ctx.window_start, ctx.window_end)
        else:
            base["open"] = _hours(p)
        base["price_inr"] = p.base_price
        if len(p.price_tiers) > 1:
            base["tiers"] = [t.model_dump() for t in p.price_tiers]
    base.update({
        "crowd": crowd_in_window(p, ctx.window_start, ctx.window_end),
        "indoor": p.indoor,
        "tags": p.tags,
        "about": p.blurb,
    })
    if p.rating:
        base["rating"] = f"{p.rating} on Google ({p.rating_count or 0:,} reviews)"
    if p.source == "swiggy":
        base["live"] = "Swiggy Scenes listing"
    if p.id in ctx.past_place_ids:
        base["memory"] = "in one of this user's past plans"
    if with_alternatives:
        alts = cheaper_alternatives(ctx, p)
        if alts:
            base["cheaper_alternatives"] = alts
    return base


def cheaper_alternatives(ctx, p: Place) -> list[dict]:
    out = []
    for alt_id in p.cheaper_alternative_ids:
        alt = ctx.places.get(alt_id)
        if alt is None or rule_violation(alt, ctx.prefs.rules) or not fits_with_travel(ctx, alt):
            continue
        ctx.seen_ids.add(alt.id)
        entry = {
            "id": alt.id, "name": alt.name, "area": alt.area,
            "price_inr": alt.base_price, "saves_inr": p.base_price - alt.base_price,
            "indoor": alt.indoor, "about": alt.blurb,
        }
        if alt.kind == "event":
            entry["start_times"] = reachable_starts(ctx, alt)
        else:
            entry["open"] = _hours(alt)
        out.append(entry)
    return out


def describe_window(ctx) -> str:
    return f"{fmt(ctx.window_start)}–{fmt(ctx.window_end)}"
