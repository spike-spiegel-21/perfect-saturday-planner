"""Swiggy Scenes MCP: live events with Saturday showtimes and ticket prices.

Scenes has no city parameter and ignores dates, so this searches by city name, keeps events whose location
is in the city, and reads Saturday's shows from list_event_shows (venue coordinates, show times, tickets,
tags). Crowd levels and indoor/outdoor aren't in the data, so they're estimated from the event's tags.
Auth is the user's own Scenes OAuth token (5 days, no refresh): get one with `python -m app.sources.swiggy_login`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from mcp import ClientSession, types
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from app.models import CityData, CrowdBySlot, Place, PriceTier

log = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

# Search queries per city: Scenes matches on the place names people see in listings.
CITY_QUERIES = {
    "bangalore": ("Bangalore", "Bengaluru"),
    "gurgaon": ("Gurgaon", "Gurugram"),
    "delhi": ("Delhi",),
    "mumbai": ("Mumbai",),
}
# The event name is the strong signal; Scenes tags are mostly internal campaign labels ("crazy 26mar").
NAME_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("comedy", ("comedy", "stand up", "standup", "stand-up", "open mic")),
    ("theatre", ("theatre", "theater", "play ", "drama", "improv")),
    ("museum", ("museum", "illusion")),
    ("workshop", ("workshop", "painting", "candle", "clay", "resin", "pottery", "craft", "masterclass", "making", "class")),
    ("food_walk", ("brunch", "menu", "kitchen", "dinner", "lunch", "happy hour", "tasting", "food", "feast", "buffet",
                   "pop-up", "popup", "chef")),
    ("music", ("hip hop", "dj", "gig", "concert", "live music", "jazz", "karaoke", "garba", "dandiya", "bollywood",
               "techno", "edm", "band", "night", "party")),
    ("gaming", ("fun world", "amusement", "arcade", "game", "trampoline", "bowling", "escape room", "vr ", "snow")),
    ("sports", ("marathon", "cricket", "football", "yoga", " run")),
    ("movie", ("screening", "film", "movie", "cinema")),
    ("art", ("exhibition", "gallery", "art show")),
    ("nature", ("trek", "hike", "birding")),
    ("walk", ("walk", "trail")),
)
TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("comedy", ("comedy",)),
    ("theatre", ("theatre", "theater")),
    ("food_walk", ("culinary", "brunch", "food tasting", "dining")),
    ("music", ("music", "nightlife", "party")),
    ("workshop", ("workshop", "art & creativity", "craft")),
    ("gaming", ("activities", "experiences")),
)
BAR_WORDS = ("happy hour", "cocktail", " bar", "pub", "brewery", "drinks", "beer", "oktoberfest")
CHILD_PASS = re.compile(r"child|kid|infant|junior", re.I)
GENDERED_PASS = re.compile(r"\b(female|women|woman|ladies|girls?)\b", re.I)  # discounted passes not everyone can buy
FETCH_TIMEOUT_S = 30
WINDOW_EVENT_MIN = 240   # events listed as longer than this are open windows (happy hours, parks): plan a typical visit
TYPICAL_VISIT_MIN = 150
GROUP_PASS = re.compile(r"\bfor\s*([2-9]|\d{2})\b|couple|group|table", re.I)


# Public event pages: https://www.swiggy.com/scenes/{category}/{name-slug}/{city}/{eventId}. The page is rendered
# from the event id; the other segments are cosmetic, so they only need to look like Swiggy's own.
EVENT_PAGE = "https://www.swiggy.com/scenes/{category}/{slug}/{city}/{event_id}"
PAGE_CATEGORY = {"comedy": "comedy", "music": "music", "workshop": "workshop", "gaming": "activities",
                 "sports": "activities"}


class ScenesError(Exception):
    pass


def event_url(event_id: str, name: str, category: str, city_key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "event"
    return EVENT_PAGE.format(category=PAGE_CATEGORY.get(category, "experiences"), slug=slug, city=city_key,
                             event_id=event_id)


async def fetch_events(city: CityData, saturday: date, *, settings, cache) -> list[Place]:
    key = f"swiggy:{city.key}:{saturday.isoformat()}"
    raw = cache.cache_get(key)
    if raw is None:
        raw = await collect(city, settings)
        cache.cache_set(key, raw, settings.events_cache_hours * 3600)
    return events_from(raw, city, saturday)


async def collect(city: CityData, settings) -> dict:
    """Raw Scenes data for a city, capped at FETCH_TIMEOUT_S so a slow connection can't stall a plan."""
    try:
        return await asyncio.wait_for(_collect(city, settings), timeout=FETCH_TIMEOUT_S)
    except asyncio.TimeoutError:
        raise ScenesError(f"Scenes took longer than {FETCH_TIMEOUT_S}s") from None


async def _collect(city: CityData, settings) -> dict:
    """Search suggestions plus the show listing of each event."""
    if not settings.swiggy_scenes_token:
        raise ScenesError("no SWIGGY_SCENES_TOKEN; run `uv run python -m app.sources.swiggy_login`")
    where = {"latitude": city.center.lat, "longitude": city.center.lng}
    headers = {"Authorization": f"Bearer {settings.swiggy_scenes_token}"}
    try:
        async with create_mcp_http_client(headers=headers) as http:
            async with streamable_http_client(settings.swiggy_scenes_url, http_client=http) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=20)
                    found: dict[str, dict] = {}
                    for query in CITY_QUERIES.get(city.key, (city.name,)):
                        res = await _call(session, "search_events", {"query": query, **where})
                        for s in res.get("suggestions") or []:
                            if _in_city(s.get("location", ""), city) and s.get("eventId"):
                                found.setdefault(str(s["eventId"]), s)
                    picked = list(found.values())[: settings.live_events_max]
                    sem = asyncio.Semaphore(3)  # stay well under Scenes' per-user request limits

                    async def shows(event_id: str):
                        async with sem:
                            return event_id, await _call(session, "list_event_shows", {"eventId": event_id, **where})

                    listings = await asyncio.gather(*(shows(str(s["eventId"])) for s in picked), return_exceptions=True)
    except ScenesError:
        raise
    except BaseException as exc:  # the transport raises exception groups; flatten to one readable error
        text = repr(exc)
        if "401" in text or "Unauthorized" in text or "-32001" in text:
            raise ScenesError("Swiggy token expired or invalid; run `uv run python -m app.sources.swiggy_login`") from None
        raise ScenesError(f"Scenes call failed: {text[:200]}") from None
    return {
        "suggestions": picked,
        "shows": {eid: listing for item in listings if not isinstance(item, BaseException) for eid, listing in [item]},
    }


async def _call(session: ClientSession, name: str, args: dict) -> dict:
    res = await session.call_tool(name, args, read_timeout_seconds=25)
    if not isinstance(res, types.CallToolResult):
        raise ScenesError(f"{name}: unexpected result {type(res).__name__}")
    text = "".join(getattr(c, "text", "") for c in res.content or [])
    if res.is_error:
        raise ScenesError(f"{name}: {text[:200]}")
    if isinstance(res.structured_content, dict) and res.structured_content:
        return res.structured_content
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise ScenesError(f"{name}: not JSON: {text[:120]}") from exc


def _in_city(location: str, city: CityData) -> bool:
    names = {city.name.lower(), city.key, *CITY_QUERIES.get(city.key, ())}
    loc = location.lower()
    return any(n.lower() in loc for n in names)


# --------------------------------------------------------------------------- mapping


def events_from(raw: dict, city: CityData, saturday: date) -> list[Place]:
    out = []
    for s in raw.get("suggestions") or []:
        listing = (raw.get("shows") or {}).get(str(s.get("eventId")))
        if listing:
            try:
                place = to_event(s, listing, city, saturday)
            except (KeyError, ValueError, TypeError) as exc:
                log.info("skipping Scenes event %s: %s", s.get("eventId"), exc)
                continue
            if place is not None:
                out.append(place)
    return out


def to_event(suggestion: dict, listing: dict, city: CityData, saturday: date) -> Place | None:
    esl = listing.get("eventShowListing") or listing
    info = esl.get("eventInfo") or {}
    venue = (esl.get("venueDetails") or [{}])[0]
    starts, tickets, span = [], [], None
    for group in esl.get("dateGroupedEventShow") or []:
        for show in group.get("eventShow") or []:
            if "SOLD_OUT" in (show.get("status") or ""):
                continue
            when = _show_start(show)
            if when is None or when.date() != saturday or not 8 <= when.hour <= 23:
                continue
            starts.append(when.strftime("%H:%M"))
            tickets = tickets or show.get("tickets") or []
            span = span or _span_min(show)
    if not starts:
        return None
    latlng = ((venue.get("location") or {}).get("latLng")) or {}
    lat, lng = latlng.get("latitude"), latlng.get("longitude")
    if lat is None or lng is None:
        return None
    name = " ".join((info.get("name") or suggestion.get("eventName") or "Live event").split())  # listings carry stray spaces
    tags_raw = [t.lower() for t in info.get("tags") or []]
    category = classify(name, tags_raw)
    tiers = _tiers(tickets)
    tags = []
    if info.get("seatingArrangement") == "SEATING_ARRANGEMENT_SEATED":
        tags.append("seated")
    if category == "music":
        tags.append("live_music")
    if any(h >= "21:00" for h in starts):
        tags.append("late_night")
    if any("kid" in t or "family" in t for t in tags_raw):
        tags.append("family")
    if any(w in f" {name.lower()} {' '.join(tags_raw)}" for w in BAR_WORDS):
        tags.append("bar")
    if min(t.price for t in tiers) == 0:
        tags.append("free")
    tags.append("social")
    outdoor = any(w in " ".join(tags_raw + [name.lower()]) for w in ("outdoor", "open air", "rooftop", "lawn", "garden"))
    busy = any(w in " ".join(tags_raw + [name.lower()]) for w in ("dj", "party", "garba", "dandiya", "concert"))
    area = venue.get("localityDisplayName") or (suggestion.get("location") or city.name).split(",")[0].strip()
    blurb = " · ".join(b for b in (
        f"at {venue.get('name')}" if venue.get("name") else "",
        info.get("ageGroup") or "",
        ", ".join(l.title() for l in info.get("languages") or []),
    ) if b)
    event_id = str(info.get("id") or suggestion["eventId"])
    return Place(
        id=f"sw_{event_id}", kind="event", name=name, area=area,
        lat=float(lat), lng=float(lng), blurb=(blurb or name)[:160], indoor=not outdoor,
        crowd=CrowdBySlot(morning="low", afternoon="low", evening="high" if busy else "medium",
                          night="high" if busy else "medium"),
        tags=sorted(set(tags)), category=category, start_times=sorted(set(starts)),
        duration_min=_duration(info, span), price_tiers=tiers, source="swiggy",
        url=event_url(event_id, name, category, city.key),
    )


def classify(name: str, tags: list[str]) -> str:
    title = f" {name.lower()} "
    for category, words in NAME_RULES:
        if any(w in title for w in words):
            return category
    tag_text = " ".join(tags)
    for category, words in TAG_RULES:
        if any(w in tag_text for w in words):
            return category
    return "music"


def _show_start(show: dict) -> datetime | None:
    if show.get("show_time_unix"):
        return datetime.fromtimestamp(int(show["show_time_unix"]), tz=IST)
    start = (show.get("timeRange") or {}).get("startTime")
    return datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(IST) if start else None


def _span_min(show: dict) -> int | None:
    rng = show.get("timeRange") or {}
    try:
        a = datetime.fromisoformat(rng["startTime"].replace("Z", "+00:00"))
        b = datetime.fromisoformat(rng["endTime"].replace("Z", "+00:00"))
        return int((b - a).total_seconds() // 60) or None
    except (KeyError, ValueError, AttributeError):
        return None


def _duration(info: dict, span: int | None) -> int:
    d = info.get("eventDuration") or {}
    value = d.get("value")
    minutes = None
    if value:
        minutes = int(float(value) * 60) if "HOUR" in (d.get("type") or "") else int(float(value))
    minutes = minutes or span or 120
    if minutes > WINDOW_EVENT_MIN:
        minutes = TYPICAL_VISIT_MIN
    return max(30, minutes)


def _tiers(tickets: list[dict]) -> list[PriceTier]:
    """Per-person ticket tiers. Group passes ("Entry Pass For 2") are skipped when a single pass exists."""
    parsed = []
    for t in tickets:
        price = t.get("price") or {}
        units = (price.get("discountedPrice") or {}).get("units") or (price.get("price") or {}).get("units") or "0"
        parsed.append((t.get("name") or "Ticket", int(float(units)), bool(GROUP_PASS.search(t.get("name") or ""))))
    adults = [x for x in parsed if not CHILD_PASS.search(x[0])] or parsed
    adults = [x for x in adults if not GENDERED_PASS.search(x[0])] or adults
    singles = [(n, p) for n, p, group in adults if not group] or [(n, p) for n, p, _ in adults]
    seen, tiers = set(), []
    for n, p in sorted(singles, key=lambda x: x[1]):
        if n.lower() not in seen:
            seen.add(n.lower())
            tiers.append(PriceTier(tier=n[:40], price=max(0, p)))
    return tiers or [PriceTier(tier="entry", price=0)]
