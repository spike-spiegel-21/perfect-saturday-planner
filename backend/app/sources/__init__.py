"""Where the agent's world comes from: live sources when configured, the mock city files otherwise.

build_city() returns the same CityData shape the tools already use, with `places` swapped for live data:
events from Swiggy Scenes, restaurants and activities from Google Places. Weather, traffic and fares stay
simulated. Each source falls back to the mock data on its own if it's unconfigured, down or empty.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.data import load_city
from app.models import CityData, Place
from app.sources.alternatives import link_cheaper_alternatives

log = logging.getLogger(__name__)


@dataclass
class SourceReport:
    events: str = "mock"          # "swiggy" | "mock"
    places: str = "mock"          # "google" | "mock"
    counts: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def dump(self) -> dict:
        return {"events": self.events, "places": self.places, "counts": self.counts, "notes": self.notes}


async def build_city(key: str, *, settings, cache, saturday) -> tuple[CityData, SourceReport]:
    base = load_city(key)
    report = SourceReport()
    mock_events = [p for p in base.places if p.kind == "event"]
    mock_rest = [p for p in base.places if p.kind != "event"]

    async def live_events():
        from app.sources.swiggy_scenes import fetch_events

        return await fetch_events(base, saturday, settings=settings, cache=cache)

    async def live_places():
        from app.sources.google_places import fetch_places

        return await fetch_places(base, settings.google_maps_api_key, cache, settings.places_cache_hours * 3600)

    async def nothing():
        return None

    # Both sources at once; each result (or failure) is handled on its own.
    got_events, got_places = await asyncio.gather(
        live_events() if settings.swiggy_enabled else nothing(),
        live_places() if settings.google_maps_api_key else nothing(),
        return_exceptions=True,
    )

    events: list[Place] = mock_events
    if isinstance(got_events, BaseException):
        log.warning("swiggy scenes unavailable: %s", got_events)
        report.notes.append(f"Swiggy Scenes unavailable ({_short(got_events)}); using sample events.")
    elif got_events:
        events, report.events = got_events, "swiggy"
    elif settings.swiggy_enabled:
        report.notes.append("Swiggy Scenes had no Saturday events for this city; using sample events.")

    rest: list[Place] = mock_rest
    if isinstance(got_places, BaseException):
        log.warning("google places unavailable: %s", got_places)
        report.notes.append(f"Google Places unavailable ({_short(got_places)}); using sample places.")
    elif got_places:
        rest, report.places = got_places, "google"

    places = [p.model_copy(deep=True) for p in events + rest]
    if report.events != "mock" or report.places != "mock":
        link_cheaper_alternatives(places)
    report.counts = {
        "events": sum(p.kind == "event" for p in places),
        "activities": sum(p.kind == "activity" for p in places),
        "restaurants": sum(p.kind == "restaurant" for p in places),
    }
    return base.model_copy(update={"places": places}), report


def _short(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    return text if len(text) <= 90 else text[:89] + "…"
