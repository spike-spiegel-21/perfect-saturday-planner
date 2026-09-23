"""Rule-based planner: builds the three options without the model.

Used when the LLM is unavailable, a loop guard trips, or submissions keep failing. It searches the same mock
data, schedules short sequences greedily and keeps what the validator accepts, so it can't invent anything.
"""

from __future__ import annotations

from itertools import permutations

from app.models import KIND_ORDER, Place, PlanItemIn, PlanOptionIn, PlanOptionOut, interest_categories, interest_restaurant_tags
from app.tools import travel
from app.tools.places import crowd_in_window, fits_window, rule_violation, score
from app.tools.validate import evaluate
from app.tools.weather import bad_reason, hour_weather, is_bad
from app.util import fmt, round5, rupees, to_min

MAX_IDLE_MIN = 90
QUALITY_BAND = 2.5  # Time Saver / Value stay within this many points of the best-fitting plan
SNACK_TAGS = {"cafe", "quick_bite", "street_food", "dessert"}


def build_fallback(ctx, kinds=KIND_ORDER, taken: dict[str, PlanOptionOut] | None = None) -> dict[str, PlanOptionOut]:
    taken = dict(taken or {})
    acts = sorted(
        (p for p in ctx.city.places if p.kind != "restaurant" and _usable(ctx, p)), key=lambda p: -_score(ctx, p)
    )[:7]
    foods = []
    if "no_restaurants" not in ctx.simulate:
        foods = sorted(
            (p for p in ctx.city.places if p.kind == "restaurant" and _usable(ctx, p)), key=lambda p: -_score(ctx, p)
        )[:5]

    seqs: list[tuple[Place, ...]] = [(a,) for a in acts]
    seqs += [(a, f) for a in acts for f in foods] + [(f, a) for a in acts for f in foods]
    seqs += [(a, f, b) for a, b in permutations(acts[:5], 2) for f in foods[:4]]
    seqs += [(a, b, f) for a, b in permutations(acts[:5], 2) for f in foods[:4]]
    seqs += list(permutations(acts[:5], 2))

    chosen: dict[str, PlanOptionOut] = {}
    used = [_key(o) for o in taken.values()]
    # recommended first: it anchors the other two
    for kind in sorted(kinds, key=lambda k: 0 if k == "recommended" else 1):
        if kind in taken:
            continue
        pool = [out for seq in seqs if (out := _evaluate_seq(ctx, seq, kind)) is not None]
        pick = _pick(ctx, kind, pool, used)
        if pick is not None:
            chosen[kind] = _dress(ctx, pick)
            used.append(_key(pick))
    return chosen


def _usable(ctx, p: Place) -> bool:
    return rule_violation(p, ctx.prefs.rules) is None and fits_window(p, ctx.window_start, ctx.window_end)


def _score(ctx, p: Place) -> float:
    s = score(ctx, p)
    if "weather_down" in ctx.simulate and p.indoor:
        s += 1.0  # no forecast: indoor is the safe bet
    return s


def _key(out: PlanOptionOut) -> tuple:
    return tuple(sorted(i.ref_id for i in out.items))


def _evaluate_seq(ctx, seq: tuple[Place, ...], kind: str) -> PlanOptionOut | None:
    opt = _schedule(ctx, seq, kind)
    return None if opt is None else evaluate(ctx, opt, grounded=False, source="fallback")


def _schedule(ctx, seq: tuple[Place, ...], kind: str) -> PlanOptionIn | None:
    t, prev, items = ctx.window_start, ctx.start_point, []
    for p in seq:
        arrive = t + travel.leg(ctx.city, prev, p, t, kind).minutes
        if p.kind == "event":
            starts = [to_min(s) for s in p.start_times if to_min(s) >= arrive]
            if not starts:
                return None
            start, duration = min(starts), p.duration_min or p.typical_min
        else:
            duration = p.typical_min
            start = _first_good_start(ctx, p, arrive, duration)
            if start is None:
                return None
        if start - arrive > MAX_IDLE_MIN:
            return None
        items.append(PlanItemIn(
            ref_id=p.id, start=fmt(start), duration_min=None if p.kind == "event" else duration,
            why_it_fits=_why(ctx, p, start),
        ))
        t, prev = start + duration, p
    return PlanOptionIn(kind=kind, title="", pitch="", items=items, tradeoffs=_tradeoffs(ctx, seq, items))


def _first_good_start(ctx, p: Place, arrive: int, duration: int) -> int | None:
    """Earliest start within opening hours, nudged later (up to the idle limit) to dodge bad weather for
    outdoor stops and to keep sit-down meals at lunch or dinner time."""
    first = None
    for o, c in p.open_hours:
        s = round5(max(arrive, to_min(o)))
        while s + duration <= to_min(c) and s - arrive <= MAX_IDLE_MIN:
            if first is None:
                first = s
            if _meal_time_ok(p, s) and not _bad_weather(ctx, p, s, duration):
                return s
            s += 15
    return first if first is not None and _meal_time_ok(p, first) else None


def _meal_time_ok(p: Place, start: int) -> bool:
    if p.kind != "restaurant" or set(p.tags) & SNACK_TAGS:
        return True
    return 12 * 60 <= start <= 15 * 60 or start >= 18 * 60 + 30


def _bad_weather(ctx, p: Place, start: int, duration: int) -> bool:
    if p.indoor or "weather_down" in ctx.simulate:
        return False
    return any((h := hour_weather(ctx.city, m)) and is_bad(h) for m in range(start, start + duration, 30))


def _pick(ctx, kind: str, pool: list[PlanOptionOut], used: list[tuple]) -> PlanOptionOut | None:
    fresh = [o for o in pool if _key(o) not in used]
    valid = [o for o in fresh if o.validation.status != "fail"]
    if not valid:
        # nothing fits: the closest plan, flagged, beats an empty screen
        return min(fresh, key=lambda o: (len(o.validation.violations), o.totals.cost_inr), default=None)
    filled = [o for o in valid if o.totals.activity_min >= 0.4 * o.totals.available_min] or valid
    ranked = sorted(filled, key=lambda o: -_plan_score(ctx, o))
    if kind == "recommended":
        return ranked[0]
    # the other two optimise travel or cost, but only among plans that still suit the user
    best = _plan_score(ctx, ranked[0])
    most = max(_interests_covered(ctx, _places(ctx, o)) for o in ranked)
    good = [o for o in ranked if _plan_score(ctx, o) >= best - QUALITY_BAND
            and _interests_covered(ctx, _places(ctx, o)) >= most - (1 if most >= 3 else 0)] or ranked[:1]
    if kind == "time_saver":
        return min(good, key=lambda o: (o.totals.travel_min, -_plan_score(ctx, o)))
    return min(good, key=lambda o: (o.totals.cost_inr, -_plan_score(ctx, o)))


def _places(ctx, out: PlanOptionOut) -> list[Place]:
    return [ctx.places[i.ref_id] for i in out.items]


def _plan_score(ctx, out: PlanOptionOut) -> float:
    places = _places(ctx, out)
    s = sum(_score(ctx, p) for p in places)
    s += 1.5 * _interests_covered(ctx, places)
    if out.totals.available_min >= 180 and any(p.kind == "restaurant" for p in places):
        s += 1.0
    s -= 2.0 * sum(_bad_weather(ctx, ctx.places[i.ref_id], to_min(i.start), i.duration_min) for i in out.items)
    s -= 0.02 * out.totals.travel_min
    s -= 0.5 * (out.validation.status == "warn")
    return s


def _interests_covered(ctx, places: list[Place]) -> int:
    covered = 0
    for interest in ctx.prefs.interests:
        word = interest.lower()
        cats = interest_categories([interest])
        tags = interest_restaurant_tags([interest])
        foodie = any(w in word for w in ("food", "eat", "cafe", "café", "coffee"))
        if any((p.kind != "restaurant" and p.category in cats) or
               (p.kind == "restaurant" and (foodie or set(p.tags) & tags)) for p in places):
            covered += 1
    return covered


def _dress(ctx, out: PlanOptionOut) -> PlanOptionOut:
    """Titles and pitches for rule-built options."""
    names = [i.name for i in out.items]
    areas = [i.area for i in out.items]
    main_area = max(areas, key=areas.count)  # ties -> the first stop's area
    part = "morning" if ctx.window_start < 12 * 60 else "afternoon" if ctx.window_start < 17 * 60 else "evening"
    if out.kind == "time_saver":
        out.title = f"Easy {part} around {main_area}"
        out.pitch = f"{len(names)} stop{'s' * (len(names) > 1)} with only {out.totals.travel_min} min of travel in total."
    elif out.kind == "value_for_money":
        share = round(100 * out.totals.cost_inr / max(1, out.totals.budget_inr))
        out.title = "Most fun per rupee"
        out.pitch = f"{rupees(out.totals.cost_inr)} all-in ({share}% of your budget), using free and cheaper picks."
    else:
        out.title = " + ".join(_short(n) for n in names[:2])
        out.pitch = f"Built around your mood ({ctx.prefs.mood}) and what you're into: {', '.join(ctx.prefs.interests)}."
    if out.validation.status == "fail":
        out.tradeoffs.append("Couldn't fit everything you asked for; this is the closest plan. See the issues below.")
    return out


def _short(name: str) -> str:
    """'Museo Camera, Centre for the Photographic Arts' -> 'Museo Camera'."""
    for sep in (":", "(", ",", " at "):
        name = name.split(sep)[0]
    return name.strip()


def _why(ctx, p: Place, start: int) -> str:
    prefs, reasons = ctx.prefs, []
    joined = [i.lower() for i in prefs.interests]
    if p.kind == "restaurant":
        if prefs.rules.vegetarian and p.veg == "pure_veg":
            reasons.append("a fully vegetarian kitchen")
        elif prefs.rules.vegetarian:
            reasons.append("plenty of vegetarian options")
        if any("food" in i for i in joined):
            reasons.append(f"{p.cuisine} for your love of food")
        elif set(p.tags) & interest_restaurant_tags(prefs.interests):
            reasons.append(f"{p.cuisine}, right up your street")
    else:
        for interest in prefs.interests:
            if p.category in interest_categories([interest]):
                reasons.append(f"matches your interest in {interest.lower()}")
                break
    if prefs.energy == "low" and {"low_effort", "seated"} & set(p.tags):
        reasons.append("easy-going, good for a tired day")
    if prefs.rules.avoid_crowds and getattr(p.crowd, "evening" if start >= 17 * 60 else "afternoon", "medium") == "low":
        reasons.append("quiet at that hour")
    h = hour_weather(ctx.city, start)
    if p.indoor and h and is_bad(h) and "weather_down" not in ctx.simulate:
        reasons.append(f"indoors, away from the {bad_reason(h)}")
    if p.base_price == 0:
        reasons.append("free entry")
    if not reasons:
        reasons.append(f"a well-rated {p.label} pick near {p.area}")
    text = "; ".join(reasons[:2])
    return text[0].upper() + text[1:] + "."


def _tradeoffs(ctx, seq: tuple[Place, ...], items: list[PlanItemIn]) -> list[str]:
    out = []
    if "no_restaurants" in ctx.simulate:
        out.append("Restaurant search came back empty, so there's no sit-down meal; grab a snack on the way.")
    if "weather_down" in ctx.simulate:
        out.append("Weather data was unavailable, so indoor-friendly picks were preferred.")
    else:
        for p, it in zip(seq, items):
            if p.indoor:
                continue
            start = to_min(it.start)
            h = hour_weather(ctx.city, start)
            if h and is_bad(h):
                out.append(f"{p.name} is outdoors during {bad_reason(h)} (weather); swap it for an indoor stop if it worsens.")
    for p, it in zip(seq, items):
        if ctx.prefs.rules.avoid_crowds is False and "high" in crowd_in_window(p, to_min(it.start), to_min(it.start) + 60).values():
            out.append(f"{p.name} gets busy around then.")
    return out
