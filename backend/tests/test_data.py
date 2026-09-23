"""The mock data is the agent's whole world, so hold it to the schema and to basic realism."""

import pytest

from app.data import SUPPORTED, load_city, resolve_city
from app.models import CATEGORIES, PLACE_TAGS
from app.util import haversine_km, to_min


@pytest.fixture(params=SUPPORTED)
def city(request):
    return load_city(request.param)


def test_counts_and_unique_ids(city):
    ids = [p.id for p in city.places]
    assert len(ids) == len(set(ids)), "duplicate place ids"
    assert all(i.startswith(city.key[:3]) for i in ids), "ids are prefixed with the city key"
    kinds = [p.kind for p in city.places]
    assert kinds.count("restaurant") >= 10
    assert kinds.count("event") + kinds.count("activity") >= 12
    assert kinds.count("event") >= 5 and kinds.count("activity") >= 5


def test_vocabularies(city):
    for p in city.places:
        assert set(p.tags) <= PLACE_TAGS, f"{p.id} has unknown tags {set(p.tags) - PLACE_TAGS}"
        if p.category:
            assert p.category in CATEGORIES


def test_times_are_valid(city):
    for p in city.places:
        for t in p.start_times:
            assert 8 * 60 <= to_min(t) <= 23 * 60, f"{p.id} start {t}"
        for open_, close in p.open_hours:
            assert to_min(open_) < to_min(close), f"{p.id} hours {open_}-{close}"
        assert 20 <= p.typical_min <= 300, f"{p.id} duration"


def test_places_sit_in_the_city(city):
    area_names = {a.name for a in city.areas}
    for p in city.places:
        assert haversine_km(city.center.lat, city.center.lng, p.lat, p.lng) < 35, f"{p.id} too far from centre"
        assert p.area in area_names, f"{p.id} area {p.area!r} is not one of the city's areas"


def test_cheaper_alternatives_exist_and_are_cheaper(city):
    by_id = {p.id: p for p in city.places}
    with_alts = 0
    for p in city.places:
        for alt_id in p.cheaper_alternative_ids:
            assert alt_id in by_id, f"{p.id} -> unknown alternative {alt_id}"
            alt = by_id[alt_id]
            assert alt.id != p.id
            assert (alt.kind == "restaurant") == (p.kind == "restaurant"), f"{p.id} -> {alt_id} crosses food/activity"
            assert alt.base_price < p.base_price, f"{alt_id} is not cheaper than {p.id}"
        with_alts += bool(p.cheaper_alternative_ids)
    assert with_alts >= 10, "most paid places should list a cheaper alternative"


def test_constraint_coverage(city):
    rest = [p for p in city.places if p.kind == "restaurant"]
    assert sum(p.veg == "pure_veg" for p in rest) >= 4, "enough pure-veg places for vegetarian users"
    assert any("vegan_options" in p.tags for p in rest)
    assert any("jain_options" in p.tags for p in rest)
    acts = [p for p in city.places if p.kind != "restaurant"]
    assert sum(p.base_price == 0 for p in acts) >= 3, "free activities for tiny budgets"
    assert sum(p.indoor for p in acts) >= 5, "indoor options for bad weather"
    assert sum(p.crowd.evening != "high" for p in acts) >= 5, "quiet options for crowd-averse users"
    assert sum("wheelchair_accessible" in p.tags for p in city.places) >= 4


def test_weather_covers_the_day(city):
    hours = [h.hour for h in city.weather.hourly]
    assert hours == list(range(8, 24))


def test_resolve_city_aliases():
    assert resolve_city("Bengaluru").key == "bangalore"
    assert resolve_city("gurugram").key == "gurgaon"
    assert resolve_city("New Delhi").key == "delhi"
    assert resolve_city("Bombay").key == "mumbai"
    assert resolve_city("Jaipur") is None
