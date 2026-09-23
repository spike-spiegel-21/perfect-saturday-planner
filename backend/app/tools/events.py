"""search_events: live events (fixed showtimes) and open-ended activities, with cheaper alternatives."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from app.models import Category
from app.tools.places import compact, fits_window, rule_violation, score
from app.util import haversine_km

MAX_RESULTS = 6


class EventsArgs(BaseModel):
    categories: list[Category] = Field(
        default_factory=list, description="categories matching the user's interests; empty means all"
    )
    max_price: int | None = Field(None, ge=0, description="max price per person in INR (cheapest ticket tier)")
    indoor_only: bool = Field(False, description="only indoor places, e.g. when rain, heat or AQI is bad")
    area: str | None = Field(None, description="optional neighbourhood to stay close to")


DESCRIPTION = (
    "Search Saturday's events (gigs, comedy, movies, theatre, workshops, guided walks, with start times and "
    "duration) and open-ended activities (parks, museums, markets, gaming, with opening hours) in the user's "
    "city and time window. Dietary, alcohol and accessibility constraints are applied automatically. Each result "
    "includes crowd levels in the window and cheaper_alternatives (similar but cheaper)."
)


async def search_events(ctx, args: EventsArgs) -> dict:
    hidden: Counter = Counter()
    usable = []
    for p in ctx.city.places:
        if p.kind == "restaurant":
            continue
        if reason := rule_violation(p, ctx.prefs.rules):
            hidden[reason] += 1
        elif not fits_window(p, ctx.window_start, ctx.window_end):
            hidden["outside your time window"] += 1
        elif args.indoor_only and not p.indoor:
            hidden["outdoor"] += 1
        else:
            usable.append(p)

    def rank(p):
        s = score(ctx, p)
        if args.area:
            anchor = next((a for a in ctx.city.areas if a.name.lower() == args.area.lower()), None)
            if anchor:
                s -= 0.3 * haversine_km(anchor.lat, anchor.lng, p.lat, p.lng)
        return -s

    matched = [p for p in usable if not args.categories or p.category in args.categories]
    note = None
    if args.categories and len(matched) < 3:
        extra = sorted((p for p in usable if p not in matched), key=rank)[: 4 - len(matched)]
        if extra:
            note = "few exact category matches; added the closest other options"
        matched += extra
    else:
        hidden["other categories"] += len(usable) - len(matched)

    affordable = [p for p in matched if args.max_price is None or p.base_price <= args.max_price]
    hidden["over max_price"] += len(matched) - len(affordable)
    ranked = sorted(affordable, key=rank)[:MAX_RESULTS]
    return {
        "count": len(ranked),
        "results": [compact(ctx, p) for p in ranked],
        "hidden": {k: v for k, v in hidden.items() if v},
        **({"note": note} if note else {}),
    }


def summarize(result: dict) -> str:
    items = result.get("results", [])
    if not items:
        return "no matches" + (f" (hidden: {result['hidden']})" if result.get("hidden") else "")
    cats = sorted({i.get("category", "") for i in items})
    prices = [i.get("price_inr", 0) for i in items]
    alts = sum(len(i.get("cheaper_alternatives", [])) for i in items)
    return f"{len(items)} options ({', '.join(cats)}) ₹{min(prices)}–₹{max(prices)} · {alts} cheaper alternatives"
