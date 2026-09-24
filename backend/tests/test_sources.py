"""Live data mappers (recorded Swiggy Scenes responses, a synthetic Google Places payload) and the fallbacks."""

import json
from datetime import date
from pathlib import Path

from app.config import Settings
from app.data import load_city
from app.memory import Store
from app.sources import build_city
from app.sources.alternatives import link_cheaper_alternatives
from app.sources.google_places import cost_for_one, saturday_hours, to_activity, to_restaurant
from app.sources.swiggy_scenes import _tiers, classify, event_url, events_from

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "swiggy_scenes_delhi.json").read_text())
SATURDAY = date(2026, 9, 26)


def _scenes_raw() -> dict:
    shows = {str(x["input"]["eventId"]): x["result"] for x in FIXTURE["list_event_shows"]}
    return {"suggestions": [{"eventId": k, "eventName": "", "location": "Delhi"} for k in shows], "shows": shows}


def test_scenes_events_keep_only_saturday_shows_in_ist():
    events = events_from(_scenes_raw(), load_city("delhi"), SATURDAY)
    assert events, "the recorded listings have Saturday shows"
    for e in events:
        assert e.kind == "event" and e.source == "swiggy" and e.id.startswith("sw_")
        assert e.start_times and all("08:00" <= t <= "23:59" for t in e.start_times)
        assert e.price_tiers and 30 <= e.duration_min <= 300
        assert 28.3 < e.lat < 28.9 and 76.8 < e.lng < 77.5  # the venue's own coordinates, in Delhi
    assert not events_from(_scenes_raw(), load_city("delhi"), date(2026, 12, 5))


def test_scenes_categories_and_group_passes():
    assert classify("Late Night StandUp Comedy Show", []) == "comedy"
    assert classify("Afterhours Saturday Ft DJ Mann", ["dj night"]) == "music"
    assert classify("Beginner Pottery Workshop", []) == "workshop"
    tiers = _tiers([
        {"name": "Entry Pass For 2", "price": {"price": {"units": "499"}}},
        {"name": "Entry Pass For 1", "price": {"price": {"units": "299"}, "discountedPrice": {"units": "249"}}},
    ])
    assert [(t.tier, t.price) for t in tiers] == [("Entry Pass For 1", 249)]


GOOGLE_RAW = {
    "id": "ChIJabc", "displayName": {"text": "Vidyarthi Bhavan"}, "location": {"latitude": 12.9453, "longitude": 77.5713},
    "types": ["south_indian_restaurant", "restaurant", "food"], "primaryType": "south_indian_restaurant",
    "primaryTypeDisplayName": {"text": "South Indian Restaurant"}, "rating": 4.5, "userRatingCount": 30210,
    "priceRange": {"startPrice": {"units": "200"}, "endPrice": {"units": "400"}}, "servesVegetarianFood": True,
    "accessibilityOptions": {"wheelchairAccessibleEntrance": True}, "googleMapsUri": "https://maps.google.com/?cid=1",
    "addressComponents": [{"longText": "Basavanagudi", "types": ["sublocality_level_1", "sublocality"]}],
    "regularOpeningHours": {"periods": [
        {"open": {"day": 6, "hour": 6, "minute": 30}, "close": {"day": 6, "hour": 11, "minute": 30}},
        {"open": {"day": 6, "hour": 14, "minute": 0}, "close": {"day": 6, "hour": 20, "minute": 0}},
        {"open": {"day": 0, "hour": 7, "minute": 0}, "close": {"day": 0, "hour": 12, "minute": 0}},
    ]},
}


def test_google_restaurant_mapping():
    p = to_restaurant(GOOGLE_RAW, load_city("bangalore"))
    assert p.source == "google" and p.cuisine == "South Indian" and p.cost_for_one == 300
    assert p.open_hours == [("06:30", "11:30"), ("14:00", "20:00")]  # Saturday only
    assert p.veg == "veg_friendly" and p.area == "Basavanagudi" and p.rating == 4.5
    assert {"wheelchair_accessible", "iconic"} <= set(p.tags) and p.crowd.evening == "high"
    assert p.url.startswith("https://maps.google.com")


def test_google_activity_mapping_and_estimates():
    park = {**GOOGLE_RAW, "id": "ChIJpark", "displayName": {"text": "Cubbon Park"}, "types": ["park"], "primaryType": "park",
            "priceRange": None, "userRatingCount": 900, "regularOpeningHours": None}
    p = to_activity(park, load_city("bangalore"), "walk")
    assert p.kind == "activity" and p.category == "walk" and not p.indoor
    assert p.base_price == 0 and "free" in p.tags and p.open_hours == [("06:00", "19:00")]
    cafe_in_museum = {**park, "types": ["cafe", "museum"]}
    assert to_activity(cafe_in_museum, load_city("bangalore"), "museum") is None


def test_google_hours_edge_cases():
    assert saturday_hours({"regularOpeningHours": {"periods": [{"open": {"day": 6, "hour": 0}}]}}) == [("00:00", "23:59")]
    late = {"regularOpeningHours": {"periods": [{"open": {"day": 6, "hour": 18}, "close": {"day": 0, "hour": 1}}]}}
    assert saturday_hours(late) == [("18:00", "23:59")]
    assert cost_for_one({"priceLevel": "PRICE_LEVEL_MODERATE"}) == 600 and cost_for_one({}) == 500


def test_cheaper_alternatives_are_linked_for_live_data():
    places = [p.model_copy(update={"cheaper_alternative_ids": []}) for p in load_city("bangalore").places]
    link_cheaper_alternatives(places)
    by_id = {p.id: p for p in places}
    linked = [p for p in places if p.cheaper_alternative_ids]
    assert linked
    for p in linked:
        for alt in p.cheaper_alternative_ids:
            assert by_id[alt].base_price < p.base_price and (by_id[alt].kind == "restaurant") == (p.kind == "restaurant")


async def test_build_city_without_keys_is_the_mock_city(tmp_path):
    city, report = await build_city("gurgaon", settings=Settings(), cache=Store(str(tmp_path / "c.db")), saturday=SATURDAY)
    assert report.events == "mock" and report.places == "mock"
    assert len(city.places) == len(load_city("gurgaon").places)


async def test_build_city_falls_back_per_source(tmp_path, monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("down")

    monkeypatch.setattr("app.sources.google_places.fetch_places", boom)
    monkeypatch.setattr("app.sources.swiggy_scenes.fetch_events", boom)
    settings = Settings(google_maps_api_key="k", swiggy_scenes_token="t")
    city, report = await build_city("delhi", settings=settings, cache=Store(str(tmp_path / "c.db")), saturday=SATURDAY)
    assert report.events == "mock" and report.places == "mock" and len(report.notes) == 2
    assert city.places


async def test_live_sources_replace_mock_places(tmp_path, monkeypatch):
    live_event = events_from(_scenes_raw(), load_city("delhi"), SATURDAY)

    async def events(*_a, **_k):
        return live_event

    async def places(*_a, **_k):
        return [to_restaurant({**GOOGLE_RAW, "location": {"latitude": 28.6, "longitude": 77.2}}, load_city("delhi"))]

    monkeypatch.setattr("app.sources.swiggy_scenes.fetch_events", events)
    monkeypatch.setattr("app.sources.google_places.fetch_places", places)
    settings = Settings(google_maps_api_key="k", swiggy_scenes_token="t")
    city, report = await build_city("delhi", settings=settings, cache=Store(str(tmp_path / "c.db")), saturday=SATURDAY)
    assert report.events == "swiggy" and report.places == "google"
    assert {p.source for p in city.places} == {"swiggy", "google"}


def test_scenes_classifier_prefers_the_event_name():
    assert classify("Hip Hop Nights At KICO Bangalore", ["board-games", "culinary"]) == "music"
    assert classify("Fun World Bangalore", ["activities", "experiences"]) == "gaming"
    assert classify("Clay Trinket Tray Date - Bangalore", ["activity summer", "workshop 08"]) == "workshop"
    assert classify("Monsoon at Yazu Bangalore", ["activities", "workshop_08", "culinary_07"]) == "food_walk"
    tiers = _tiers([
        {"name": "Children Pass (80 cm to 120 cm)", "price": {"price": {"units": "999"}}},
        {"name": "Adult Pass (Above 120 cm)", "price": {"price": {"units": "1199"}}},
    ])
    assert [t.price for t in tiers] == [1199]


def test_scenes_events_link_to_their_swiggy_page():
    assert event_url("100067798", "Vivek Samtani Live", "comedy", "bangalore") == \
        "https://www.swiggy.com/scenes/comedy/vivek-samtani-live/bangalore/100067798"
    assert event_url("1", "Ladakh's Alchi Kitchen - Nila!", "food_walk", "delhi") == \
        "https://www.swiggy.com/scenes/experiences/ladakh-s-alchi-kitchen-nila/delhi/1"
    for e in events_from(_scenes_raw(), load_city("delhi"), SATURDAY):
        assert e.url.startswith("https://www.swiggy.com/scenes/") and e.url.endswith("/" + e.id.removeprefix("sw_"))
