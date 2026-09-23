"""Where the agent's world comes from: live sources when configured, the mock city files otherwise.

build_city() returns the same CityData shape the tools already use, with `places` swapped for live data:
events from Swiggy Scenes, restaurants and activities from Google Places. Weather, traffic and fares stay
simulated. Each source falls back to the mock data on its own if it's unconfigured, down or empty.
"""

from __future__ import annotations

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

    events: list[Place] = mock_events
    if settings.swiggy_enabled:
        try:
            from app.sources.swiggy_scenes import fetch_events

            live = await fetch_events(base, saturday, settings=settings, cache=cache)
            if live:
                events, report.events = live, "swiggy"
            else:
                report.notes.append("Swiggy Scenes had no Saturday events for this city; using sample events.")
        except Exception as exc:  # any failure: keep the mock events, say so in the trace
            log.warning("swiggy scenes unavailable: %s", exc)
            report.notes.append(f"Swiggy Scenes unavailable ({exc.__class__.__name__}); using sample events.")

    rest: list[Place] = mock_rest
    if settings.google_maps_api_key:
        try:
            from app.sources.google_places import fetch_places

            live = await fetch_places(base, settings.google_maps_api_key, cache, settings.places_cache_hours * 3600)
            if live:
                rest, report.places = live, "google"
        except Exception as exc:
            log.warning("google places unavailable: %s", exc)
            report.notes.append(f"Google Places unavailable ({exc.__class__.__name__}); using sample places.")

    places = [p.model_copy(deep=True) for p in events + rest]
    if report.events != "mock" or report.places != "mock":
        link_cheaper_alternatives(places)
    report.counts = {
        "events": sum(p.kind == "event" for p in places),
        "activities": sum(p.kind == "activity" for p in places),
        "restaurants": sum(p.kind == "restaurant" for p in places),
    }
    return base.model_copy(update={"places": places}), report
