"""Small time and geo helpers. Times are minutes since midnight on Saturday."""

from __future__ import annotations

import math
import re
from datetime import date, timedelta

_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def to_min(hhmm: str) -> int:
    m = _HHMM.match(hhmm.strip())
    if not m:
        raise ValueError(f"bad time {hhmm!r}, expected HH:MM")
    return int(m.group(1)) * 60 + int(m.group(2))


def is_hhmm(value: str | None) -> bool:
    return bool(value and _HHMM.match(value.strip()))


def fmt(minutes: int) -> str:
    minutes = max(0, int(round(minutes)))
    h, m = divmod(minutes, 60)
    if h >= 24:  # past midnight still reads as a clock time
        h -= 24
    return f"{h:02d}:{m:02d}"


def round5(minutes: float) -> int:
    return int(math.ceil(minutes / 5.0) * 5)


def slot_of(minute: int) -> str:
    """Crowd/traffic slot for a time: morning <12, afternoon 12-17, evening 17-21, night >=21."""
    hour = (minute // 60) % 24
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 21:
        return "evening"
    return "night"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def next_saturday(today: date | None = None) -> date:
    today = today or date.today()
    days = (5 - today.weekday()) % 7  # Monday=0 ... Saturday=5; today if it is Saturday
    return today + timedelta(days=days)


def rupees(amount: int) -> str:
    return f"₹{amount:,}"
