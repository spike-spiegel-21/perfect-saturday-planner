"""search_restaurants: places to eat, priced for one person, with cheaper alternatives."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from app.tools.places import compact, fits_window, rule_violation, score
from app.util import haversine_km

MAX_RESULTS = 6


class RestaurantArgs(BaseModel):
    max_cost_for_one: int | None = Field(None, ge=0, description="max spend for one person in INR")
    area: str | None = Field(None, description="optional neighbourhood to stay close to")
    cuisine: str | None = Field(None, description="optional cuisine or style, e.g. 'south indian', 'cafe', 'dessert'")


DESCRIPTION = (
    "Search restaurants and cafés open during the user's window, priced as cost for ONE person. Vegetarian / "
    "vegan / jain / no-alcohol / accessibility constraints are applied automatically. Each result includes crowd "
    "levels in the window and cheaper_alternatives."
)


async def search_restaurants(ctx, args: RestaurantArgs) -> dict:
    if "no_restaurants" in ctx.simulate:
        return {"count": 0, "results": [], "note": "no restaurants matched (simulated empty result): plan without a sit-down meal"}
    hidden: Counter = Counter()
    usable = []
    for p in ctx.city.places:
        if p.kind != "restaurant":
            continue
        if reason := rule_violation(p, ctx.prefs.rules):
            hidden[reason] += 1
        elif not fits_window(p, ctx.window_start, ctx.window_end):
            hidden["closed during your window"] += 1
        else:
            usable.append(p)

    def rank(p):
        s = score(ctx, p)
        if args.cuisine:
            want = args.cuisine.lower()
            if want in (p.cuisine or "").lower() or any(want in t for t in p.tags):
                s += 2
        if args.area:
            anchor = next((a for a in ctx.city.areas if a.name.lower() == args.area.lower()), None)
            if anchor:
                s -= 0.3 * haversine_km(anchor.lat, anchor.lng, p.lat, p.lng)
        return -s

    affordable = [p for p in usable if args.max_cost_for_one is None or (p.cost_for_one or 0) <= args.max_cost_for_one]
    hidden["over max_cost_for_one"] += len(usable) - len(affordable)
    ranked = sorted(affordable, key=rank)[:MAX_RESULTS]
    return {
        "count": len(ranked),
        "results": [compact(ctx, p) for p in ranked],
        "hidden": {k: v for k, v in hidden.items() if v},
    }


def summarize(result: dict) -> str:
    items = result.get("results", [])
    if not items:
        return result.get("note") or "no matches"
    costs = [i["cost_for_one"] for i in items]
    veg = sum(i.get("veg") == "pure_veg" for i in items)
    return f"{len(items)} places ₹{min(costs)}–₹{max(costs)} for one · {veg} pure-veg"
