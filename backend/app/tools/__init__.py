"""The agent's tools. Each is a mock today; swapping one for a real API means rewriting one handler."""

from app.tools.registry import Tool  # noqa: I001  (import first: the tool modules depend on it)
from app.tools import events, restaurants, travel, validate, weather


def build_tools() -> dict[str, Tool]:
    tools = [
        Tool("get_weather", weather.DESCRIPTION, weather.WeatherArgs, weather.get_weather, weather.summarize),
        Tool("search_events", events.DESCRIPTION, events.EventsArgs, events.search_events, events.summarize),
        Tool("search_restaurants", restaurants.DESCRIPTION, restaurants.RestaurantArgs,
             restaurants.search_restaurants, restaurants.summarize),
        Tool("get_travel", travel.DESCRIPTION, travel.TravelArgs, travel.get_travel, travel.summarize),
        Tool("validate_plan", validate.VALIDATE_DESCRIPTION, validate.ValidateArgs, validate.validate_plan,
             validate.summarize_validate),
        Tool("submit_plans", validate.SUBMIT_DESCRIPTION, validate.SubmitArgs, validate.submit_plans,
             validate.summarize_submit),
    ]
    return {t.name: t for t in tools}
