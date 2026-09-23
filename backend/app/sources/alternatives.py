"""Cheaper alternatives for live data, which (unlike the hand-written mock data) doesn't come with them."""

from __future__ import annotations

from app.models import Place
from app.util import haversine_km


def link_cheaper_alternatives(places: list[Place], per_place: int = 2) -> None:
    """For every paid place, point at up to two cheaper places of the same kind of outing, nearest first."""
    for p in places:
        if p.cheaper_alternative_ids or p.base_price == 0:
            continue
        same = [q for q in places if q.id != p.id and _same_group(p, q) and q.base_price < p.base_price]
        same.sort(key=lambda q: (not _same_flavour(p, q), haversine_km(p.lat, p.lng, q.lat, q.lng)))
        p.cheaper_alternative_ids = [q.id for q in same[:per_place]]


def _same_group(a: Place, b: Place) -> bool:
    return (a.kind == "restaurant") == (b.kind == "restaurant")


def _same_flavour(a: Place, b: Place) -> bool:
    if a.kind == "restaurant":
        return bool({"cafe", "dessert", "street_food", "fine_dining"} & set(a.tags) & set(b.tags)) or a.cuisine == b.cuisine
    return a.category == b.category
