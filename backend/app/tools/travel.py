"""get_travel: distance, time and fare between two points (mock: haversine x road factor, city speeds)."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.models import Area, CityData, Leg, Place
from app.util import haversine_km, round5, slot_of, to_min

ROAD_FACTOR = 1.35
WALK_KMPH = 4.5
WALK_MAX_KM = 2.0
METRO_MIN_KM = 5.0


@dataclass(frozen=True)
class ModeOption:
    mode: str
    minutes: int
    fare_inr: int


def _fare(amount: float) -> int:
    return int(round(amount / 5.0) * 5)


def mode_options(city: CityData, a: Area | Place, b: Area | Place, depart_min: int) -> tuple[float, list[ModeOption]]:
    km = max(0.2, haversine_km(a.lat, a.lng, b.lat, b.lng) * ROAD_FACTOR)
    speed = city.traffic_kmph.get(slot_of(depart_min), 20.0)
    f = city.fares
    opts: list[ModeOption] = []
    if km <= WALK_MAX_KM:
        opts.append(ModeOption("walk", round5(km / WALK_KMPH * 60), 0))
    opts.append(ModeOption("auto", round5(km / speed * 60 + 4), _fare(f.auto_base + f.auto_per_km * km)))
    surge = 1.2 if slot_of(depart_min) == "evening" else 1.0
    opts.append(ModeOption("cab", round5(km / (speed * 1.05) * 60 + 6), _fare((f.cab_base + f.cab_per_km * km) * surge)))
    if f.metro and km >= METRO_MIN_KM:
        opts.append(ModeOption("metro", round5(km / 32 * 60 + 18), _fare(min(60, 10 + 2.5 * km))))
    return round(km, 1), opts


def suggested(opts: list[ModeOption], km: float) -> ModeOption:
    by = {o.mode: o for o in opts}
    if "walk" in by and km <= 1.2:
        return by["walk"]
    if km <= 8:
        return by["auto"]
    if "metro" in by and by["metro"].minutes <= by["cab"].minutes + 15:
        return by["metro"]
    return by["cab"]


def pick(opts: list[ModeOption], km: float, policy: str) -> ModeOption:
    """Mode policy per option kind: Time Saver rides fastest, Value rides cheapest-sensible."""
    if policy == "time_saver":
        return min(opts, key=lambda o: (o.minutes, o.fare_inr))
    if policy == "value_for_money":
        fastest = min(o.minutes for o in opts)
        ok = [o for o in opts if o.minutes <= fastest * 1.6 + 10]
        return min(ok, key=lambda o: (o.fare_inr, o.minutes))
    return suggested(opts, km)


def leg(city: CityData, a: Area | Place, b: Area | Place, depart_min: int, policy: str) -> Leg:
    km, opts = mode_options(city, a, b, depart_min)
    choice = pick(opts, km, policy)
    return Leg(from_name=a.name, to_name=b.name, mode=choice.mode, km=km, minutes=choice.minutes, fare_inr=choice.fare_inr)


# --------------------------------------------------------------------------- tool


class LegRequest(BaseModel):
    from_id: str = Field(description='place id, or "start" for the user\'s starting point')
    to_id: str = Field(description='place id, or "start" for the ride back')
    depart: str | None = Field(None, description="departure time HH:MM (traffic varies by time of day)")


class TravelArgs(BaseModel):
    legs: list[LegRequest] = Field(min_length=1, max_length=10)


DESCRIPTION = (
    "Distance, travel time and fare between two points for walk / auto / cab / metro, with a suggested mode. "
    "Pass several legs at once. Use \"start\" for the user's starting point."
)


async def get_travel(ctx, args: TravelArgs) -> dict:
    out = []
    for req in args.legs:
        a = _point(ctx, req.from_id)
        b = _point(ctx, req.to_id)
        if a is None or b is None:
            out.append({"from": req.from_id, "to": req.to_id, "error": "unknown place id"})
            continue
        try:
            depart = to_min(req.depart) if req.depart else ctx.window_start
        except ValueError:
            depart = ctx.window_start
        km, opts = mode_options(ctx.city, a, b, depart)
        out.append({
            "from": req.from_id, "to": req.to_id, "km": km,
            "options": [{"mode": o.mode, "minutes": o.minutes, "fare_inr": o.fare_inr} for o in opts],
            "suggested": suggested(opts, km).mode,
        })
    return {"legs": out, "note": "the validator uses: time_saver -> fastest, recommended -> suggested, value_for_money -> cheapest sensible"}


def _point(ctx, ref: str):
    if ref.strip().lower() in {"start", "home", "start_point"}:
        return ctx.start_point
    return ctx.places.get(ref)


def summarize(result: dict) -> str:
    parts = []
    for lg in result.get("legs", [])[:4]:
        if "error" in lg:
            parts.append(f"{lg['from']}→{lg['to']}: unknown")
            continue
        best = next((o for o in lg["options"] if o["mode"] == lg["suggested"]), lg["options"][0])
        parts.append(f"{lg['km']} km {best['mode']} {best['minutes']}m ₹{best['fare_inr']}")
    more = len(result.get("legs", [])) - 4
    return "; ".join(parts) + (f" (+{more} more)" if more > 0 else "")
