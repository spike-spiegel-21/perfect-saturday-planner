"""Google Places API (New): real restaurants and activities for a city.

Google gives names, coordinates, Saturday opening hours, ratings, price range, vegetarian and accessibility
flags. What it doesn't have (crowd levels, entry prices for parks and museums, visit length) is estimated
here from the place type and its popularity, so the rest of the agent sees one consistent Place shape.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from app.models import CityData, CrowdBySlot, Place, PriceTier
from app.util import to_min

log = logging.getLogger(__name__)

URL = "https://places.googleapis.com/v1/places:searchText"
FIELDS = ",".join(f"places.{f}" for f in (
    "id", "displayName", "location", "shortFormattedAddress", "formattedAddress", "addressComponents", "types",
    "primaryType", "primaryTypeDisplayName", "businessStatus", "googleMapsUri", "rating", "userRatingCount",
    "priceLevel", "priceRange", "regularOpeningHours", "servesVegetarianFood", "servesBeer", "servesWine",
    "servesCocktails", "liveMusic", "accessibilityOptions", "editorialSummary", "goodForChildren",
))
SEARCH_RADIUS_M = 15_000

# (query, includedType or None, our kind, our category for activities)
QUERIES: tuple[tuple[str, str | None, str, str | None], ...] = (
    ("vegetarian restaurants", "restaurant", "restaurant", None),
    ("popular restaurants", "restaurant", "restaurant", None),
    ("cafes", "cafe", "restaurant", None),
    ("street food and chaat", None, "restaurant", None),
    ("desserts and ice cream", None, "restaurant", None),
    ("parks and gardens", "park", "activity", "walk"),
    ("museums", "museum", "activity", "museum"),
    ("art galleries", "art_gallery", "activity", "art"),
    ("historical monuments", None, "activity", "heritage"),
    ("bookstores", "book_store", "activity", "books"),
    ("shopping malls", "shopping_mall", "activity", "shopping"),
    ("bowling and gaming arcades", None, "activity", "gaming"),
    ("flea markets and bazaars", None, "activity", "market"),
)

PRICE_LEVEL_INR = {
    "PRICE_LEVEL_FREE": 0, "PRICE_LEVEL_INEXPENSIVE": 250, "PRICE_LEVEL_MODERATE": 600,
    "PRICE_LEVEL_EXPENSIVE": 1200, "PRICE_LEVEL_VERY_EXPENSIVE": 2200,
}
# Estimates for what Places doesn't provide: entry price (INR) and a typical visit length (min).
ACTIVITY_DEFAULTS = {
    "walk": (0, 60), "nature": (30, 90), "museum": (150, 90), "art": (0, 60), "heritage": (40, 75),
    "books": (0, 45), "shopping": (0, 90), "gaming": (600, 90), "market": (0, 60),
}
OUTDOOR_CATEGORIES = {"walk", "nature", "heritage", "market"}


class PlacesError(Exception):
    pass


async def fetch_places(city: CityData, api_key: str, cache, ttl_s: float) -> list[Place]:
    """All restaurants and activities for a city (deduplicated), from cache when fresh."""
    async with httpx.AsyncClient(timeout=10) as client:
        batches = await asyncio.gather(
            *(_search(client, api_key, city, q, t, cache, ttl_s) for q, t, _, _ in QUERIES), return_exceptions=True
        )
    failures = [b for b in batches if isinstance(b, Exception)]
    if len(failures) == len(batches):
        raise PlacesError(f"all Places queries failed: {failures[0]}")
    for f in failures:
        log.warning("places query failed: %s", f)

    places: dict[str, Place] = {}
    for (query, _type, kind, category), raw_list in zip(QUERIES, batches):
        if isinstance(raw_list, Exception):
            continue
        for raw in raw_list:
            pid = "g_" + raw.get("id", "")
            if pid in places or raw.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
                continue
            try:
                place = to_restaurant(raw, city) if kind == "restaurant" else to_activity(raw, city, category or "walk")
            except (KeyError, ValueError, TypeError) as exc:
                log.info("skipping place %s: %s", raw.get("id"), exc)
                continue
            if place is not None:
                places[pid] = place
    return list(places.values())


async def _search(client, api_key, city, query, included_type, cache, ttl_s) -> list[dict]:
    key = f"google:{city.key}:{query}"
    if (hit := cache.cache_get(key)) is not None:
        return hit
    body: dict = {
        "textQuery": f"{query} in {city.name}",
        "pageSize": 20,
        "regionCode": "IN",
        "languageCode": "en",
        "locationBias": {"circle": {"center": {"latitude": city.center.lat, "longitude": city.center.lng},
                                    "radius": SEARCH_RADIUS_M}},
    }
    if included_type:
        body["includedType"] = included_type
    resp = await client.post(URL, json=body, headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS})
    if resp.status_code != 200:
        raise PlacesError(f"{query}: HTTP {resp.status_code} {resp.text[:200]}")
    places = resp.json().get("places", [])
    cache.cache_set(key, places, ttl_s)
    return places


# --------------------------------------------------------------------------- mapping


def to_restaurant(raw: dict, city: CityData) -> Place | None:
    types = set(raw.get("types") or [])
    primary = raw.get("primaryType") or ""
    hours = saturday_hours(raw) or [("11:00", "23:00")]
    name_l = _name(raw).lower()
    if (primary in {"vegetarian_restaurant", "vegan_restaurant"} or "vegetarian_restaurant" in types
            or "pure veg" in name_l or "vegetarian" in name_l):
        veg = "pure_veg"
    elif raw.get("servesVegetarianFood") is False:
        veg = "non_veg"
    else:
        veg = "veg_friendly"  # Indian restaurants almost always have veg dishes; Google often leaves this blank
    tags = _common_tags(raw)
    if types & {"cafe", "coffee_shop"} or primary in {"cafe", "coffee_shop"}:
        tags.append("cafe")
    if types & {"dessert_shop", "ice_cream_shop", "bakery", "dessert_restaurant", "confectionery"}:
        tags.append("dessert")
    if types & {"fast_food_restaurant", "meal_takeaway"}:
        tags.append("quick_bite")
    if "street" in _name(raw).lower() or "chaat" in _name(raw).lower():
        tags.append("street_food")
    if primary in {"bar", "pub", "night_club", "wine_bar", "cocktail_bar"} or types & {"bar", "pub", "night_club"}:
        tags.append("bar")
    if raw.get("priceLevel") in {"PRICE_LEVEL_EXPENSIVE", "PRICE_LEVEL_VERY_EXPENSIVE"} or "fine_dining_restaurant" in types:
        tags.append("fine_dining")
    if raw.get("liveMusic"):
        tags.append("live_music")
    if primary == "vegan_restaurant" or "vegan_restaurant" in types:
        tags.append("vegan_options")
    if "jain" in _name(raw).lower():
        tags.append("jain_options")
    meal = 40 if {"cafe", "dessert", "quick_bite", "street_food"} & set(tags) else (100 if "fine_dining" in tags else 70)
    return Place(
        id="g_" + raw["id"], kind="restaurant", name=_name(raw), area=area_of(raw, city),
        lat=raw["location"]["latitude"], lng=raw["location"]["longitude"], blurb=_blurb(raw), indoor=True,
        crowd=_crowd(raw.get("userRatingCount"), restaurant=True), tags=sorted(set(tags)),
        cuisine=_cuisine(raw), cost_for_one=cost_for_one(raw), veg=veg, meal_min=meal, open_hours=hours,
        source="google", url=raw.get("googleMapsUri"), rating=raw.get("rating"), rating_count=raw.get("userRatingCount"),
    )


def to_activity(raw: dict, city: CityData, category: str) -> Place | None:
    types = set(raw.get("types") or [])
    if types & {"restaurant", "cafe", "bar", "lodging"} and category not in {"shopping", "market"}:
        return None  # a query for museums sometimes returns a museum café; keep activities clean
    if category == "walk" and types & {"national_park", "hiking_area", "botanical_garden"}:
        category = "nature"
    price, minutes = ACTIVITY_DEFAULTS.get(category, (0, 60))
    if raw.get("priceLevel") in PRICE_LEVEL_INR:
        price = PRICE_LEVEL_INR[raw["priceLevel"]]
    tags = _common_tags(raw)
    if price == 0:
        tags.append("free")
    if category in {"books", "art", "museum"}:
        tags.append("low_effort")
    if category in {"nature"} and "hiking_area" in types:
        tags.append("active")
    if raw.get("goodForChildren"):
        tags.append("family")
    hours = saturday_hours(raw) or ([("06:00", "19:00")] if category in OUTDOOR_CATEGORIES else [("10:00", "20:00")])
    return Place(
        id="g_" + raw["id"], kind="activity", name=_name(raw), area=area_of(raw, city),
        lat=raw["location"]["latitude"], lng=raw["location"]["longitude"], blurb=_blurb(raw),
        indoor=category not in OUTDOOR_CATEGORIES, crowd=_crowd(raw.get("userRatingCount"), restaurant=False),
        tags=sorted(set(tags)), category=category, open_hours=hours, duration_min=minutes,
        price_tiers=[PriceTier(tier="entry", price=price)],
        source="google", url=raw.get("googleMapsUri"), rating=raw.get("rating"), rating_count=raw.get("userRatingCount"),
    )


def saturday_hours(raw: dict) -> list[tuple[str, str]]:
    """Saturday opening spans from regularOpeningHours (day 6 = Saturday)."""
    spans = []
    for period in (raw.get("regularOpeningHours") or {}).get("periods") or []:
        open_ = period.get("open") or {}
        if open_.get("day") != 6:
            continue
        close = period.get("close")
        if close is None:
            return [("00:00", "23:59")]  # open 24 hours
        start = f"{open_.get('hour', 0):02d}:{open_.get('minute', 0):02d}"
        end = f"{close.get('hour', 0):02d}:{close.get('minute', 0):02d}" if close.get("day") == 6 else "23:59"
        if to_min(end) <= to_min(start):
            end = "23:59"
        spans.append((start, end))
    return sorted(spans)


def cost_for_one(raw: dict) -> int:
    rng = raw.get("priceRange") or {}
    lo = int((rng.get("startPrice") or {}).get("units") or 0)
    hi = int((rng.get("endPrice") or {}).get("units") or 0)
    if lo or hi:
        return int(round(((lo + hi) / 2 if lo and hi else lo or hi) / 10.0) * 10)
    return PRICE_LEVEL_INR.get(raw.get("priceLevel"), 500)


def area_of(raw: dict, city: CityData) -> str:
    for comp in raw.get("addressComponents") or []:
        if set(comp.get("types") or []) & {"sublocality_level_1", "sublocality", "neighborhood"}:
            return comp.get("longText") or comp.get("shortText") or city.name
    parts = [p.strip() for p in (raw.get("shortFormattedAddress") or raw.get("formattedAddress") or "").split(",") if p.strip()]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else city.name)


def _name(raw: dict) -> str:
    return (raw.get("displayName") or {}).get("text") or "Unnamed place"


def _cuisine(raw: dict) -> str:
    label = (raw.get("primaryTypeDisplayName") or {}).get("text") or (raw.get("primaryType") or "restaurant").replace("_", " ")
    label = label.replace(" Restaurant", "").replace(" restaurant", "").strip()
    return label[:1].upper() + label[1:] if label else "Restaurant"


def _blurb(raw: dict) -> str:
    """Google's editorial summary when there is one; otherwise just the place type (the rating is shown separately)."""
    summary = (raw.get("editorialSummary") or {}).get("text")
    if summary:
        return summary[:160]
    return (raw.get("primaryTypeDisplayName") or {}).get("text") or "Listed on Google Maps"


def _common_tags(raw: dict) -> list[str]:
    tags = []
    if (raw.get("accessibilityOptions") or {}).get("wheelchairAccessibleEntrance"):
        tags.append("wheelchair_accessible")
    count, rating = raw.get("userRatingCount") or 0, raw.get("rating") or 0
    if count >= 20_000:
        tags.append("iconic")
    elif rating >= 4.5 and count < 3_000:
        tags.append("hidden_gem")
    if count < 1_500:
        tags.append("quiet")
    return tags


def _crowd(count: int | None, *, restaurant: bool) -> CrowdBySlot:
    """Google's API has no popular-times data, so busyness is estimated from how many people review a place."""
    n = count or 0
    if restaurant:
        if n > 8_000:
            return CrowdBySlot(morning="low", afternoon="medium", evening="high", night="medium")
        if n > 2_000:
            return CrowdBySlot(morning="low", afternoon="medium", evening="medium", night="low")
        return CrowdBySlot(morning="low", afternoon="low", evening="medium", night="low")
    if n > 20_000:
        return CrowdBySlot(morning="medium", afternoon="medium", evening="high", night="medium")
    if n > 5_000:
        return CrowdBySlot(morning="low", afternoon="medium", evening="medium", night="low")
    return CrowdBySlot(morning="low", afternoon="low", evening="low", night="low")
