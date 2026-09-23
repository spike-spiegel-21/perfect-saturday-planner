"""get_weather: Saturday forecast for the user's window (mock: per-city hourly data)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models import CityData, HourWeather
from app.tools.registry import ToolUnavailable

RAIN_BAD = 60
AQI_BAD = 200
HOT = 35


def is_bad(h: HourWeather) -> bool:
    return h.rain_pct >= RAIN_BAD or h.aqi >= AQI_BAD or h.temp_c >= HOT


def hour_weather(city: CityData, minute: int) -> HourWeather | None:
    hour = min(23, max(8, minute // 60))
    return next((h for h in city.weather.hourly if h.hour == hour), None)


def bad_reason(h: HourWeather) -> str:
    if h.rain_pct >= RAIN_BAD:
        return f"{h.rain_pct}% chance of rain"
    if h.aqi >= AQI_BAD:
        return f"poor air (AQI {h.aqi})"
    return f"{h.temp_c}°C heat"


def _windows(hours: list[HourWeather], good: bool) -> list[str]:
    spans, start = [], None
    for h in hours + [None]:  # sentinel closes the last span
        ok = h is not None and (not is_bad(h)) == good
        if ok and start is None:
            start = h.hour
        if not ok and start is not None:
            end = (h.hour if h is not None else hours[-1].hour + 1)
            spans.append(f"{start:02d}:00–{end:02d}:00")
            start = None
    return spans


class WeatherArgs(BaseModel):
    city: str = Field(description="the city being planned")


DESCRIPTION = (
    "Saturday's hourly weather (temperature, rain chance, AQI) inside the user's time window, "
    "with the windows when being outdoors is comfortable. Use it to choose indoor vs outdoor stops."
)


async def get_weather(ctx, args: WeatherArgs) -> dict:
    if "weather_down" in ctx.simulate:
        raise ToolUnavailable("weather service unavailable (simulated outage)")
    lo, hi = ctx.window_start // 60, min(23, ctx.window_end // 60)
    hours = [h for h in ctx.city.weather.hourly if lo <= h.hour <= hi]
    good, bad = _windows(hours, True), _windows(hours, False)
    worst = [h for h in hours if is_bad(h)]
    if worst:
        advice = f"Avoid long outdoor stops {', '.join(bad)} ({bad_reason(worst[0])}); prefer indoor then."
    else:
        advice = "Outdoor is comfortable for your whole window."
    ctx.weather_summary = f"{ctx.city.weather.summary} {advice}"
    return {
        "city": ctx.city.name,
        "date": ctx.saturday.strftime("%a %d %b"),
        "summary": ctx.city.weather.summary,
        "in_your_window": [
            {"time": f"{h.hour:02d}:00", "temp_c": h.temp_c, "rain_pct": h.rain_pct, "aqi": h.aqi} for h in hours
        ],
        "outdoor_ok": good,
        "outdoor_bad": bad,
        "advice": advice,
    }


def summarize(result: dict) -> str:
    hours = result.get("in_your_window", [])
    if not hours:
        return result.get("summary", "")
    temps = [h["temp_c"] for h in hours]
    rain = max(h["rain_pct"] for h in hours)
    aqi = max(h["aqi"] for h in hours)
    ok = ", ".join(result.get("outdoor_ok", [])) or "none"
    return f"{min(temps)}–{max(temps)}°C, rain ≤{rain}%, AQI ≤{aqi} · outdoor ok: {ok}"
