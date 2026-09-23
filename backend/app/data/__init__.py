"""Mock city data: one JSON file per supported city, loaded and validated once."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.models import CityData, Place

DATA_DIR = Path(__file__).parent
SUPPORTED = ("bangalore", "gurgaon", "delhi", "mumbai")


@lru_cache(maxsize=None)
def load_city(key: str) -> CityData:
    return CityData.model_validate(json.loads((DATA_DIR / f"{key}.json").read_text()))


def all_cities() -> list[CityData]:
    return [load_city(k) for k in SUPPORTED]


def resolve_city(text: str | None) -> CityData | None:
    """Map what the user typed ("Bengaluru", "gurugram", "New Delhi") to a supported city."""
    if not text:
        return None
    t = text.strip().lower()
    for city in all_cities():
        names = [city.key, city.name.lower(), *city.aliases]
        if t in names or any(n in t for n in names if len(n) > 3):
            return city
    return None


def place_index(city: CityData) -> dict[str, Place]:
    return {p.id: p for p in city.places}
