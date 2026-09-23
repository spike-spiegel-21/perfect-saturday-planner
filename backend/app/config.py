"""Settings from the environment (`backend/.env` locally) and the agent loop limits."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Limits:
    """Hard stops that keep the execution loop finite and cheap."""

    max_steps: int = 8                  # model calls per run
    max_tool_calls: int = 40            # tool executions per run
    caps: dict[str, int] = field(default_factory=lambda: {
        "get_weather": 2,
        "search_events": 4,
        "search_restaurants": 4,
        "get_travel": 8,                # each call can carry up to 10 legs
        "validate_plan": 6,
        "submit_plans": 3,              # the done signal; after 3 rejections the fallback fills gaps
    })
    run_deadline_s: float = 150.0
    llm_timeout_s: float = 90.0
    tool_timeout_s: float = 5.0
    max_tokens: int = 12000            # room for thinking + a full submit_plans call; only generated tokens cost


@dataclass(frozen=True)
class Settings:
    openrouter_api_key: str = ""
    model: str = "anthropic/claude-sonnet-5"
    base_url: str = "https://openrouter.ai/api/v1"
    planner_effort: str = "low"
    db_path: str = "planner.db"
    allowed_origins: tuple[str, ...] = ("http://localhost:5173",)
    allow_simulation: bool = True
    rate_user_per_day: int = 8
    rate_ip_per_day: int = 20
    rate_global_per_day: int = 150
    mock_latency_ms: int = 250
    app_url: str = "http://localhost:5173"
    limits: Limits = field(default_factory=Limits)
    # live data (each falls back to the mock city files when unset or failing)
    google_maps_api_key: str = ""
    places_cache_hours: float = 12.0
    swiggy_scenes_token: str = ""
    swiggy_scenes_url: str = "https://mcp.swiggy.com/scenes"
    events_cache_hours: float = 3.0
    live_events_max: int = 12

    @property
    def swiggy_enabled(self) -> bool:
        return bool(self.swiggy_scenes_token)


def load_settings() -> Settings:
    origins = tuple(o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip())
    return Settings(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        model=os.getenv("MODEL", "anthropic/claude-sonnet-5"),
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        planner_effort=os.getenv("PLANNER_EFFORT", "low"),
        db_path=os.getenv("DB_PATH", "planner.db"),
        allowed_origins=origins,
        allow_simulation=_bool("ALLOW_SIMULATION", True),
        rate_user_per_day=_int("RATE_USER_PER_DAY", 8),
        rate_ip_per_day=_int("RATE_IP_PER_DAY", 20),
        rate_global_per_day=_int("RATE_GLOBAL_PER_DAY", 150),
        mock_latency_ms=_int("MOCK_LATENCY_MS", 250),
        app_url=os.getenv("APP_URL", "http://localhost:5173"),
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY", "").strip(),
        places_cache_hours=float(os.getenv("PLACES_CACHE_HOURS", "12")),
        swiggy_scenes_token=os.getenv("SWIGGY_SCENES_TOKEN", "").strip(),
        swiggy_scenes_url=os.getenv("SWIGGY_SCENES_URL", "https://mcp.swiggy.com/scenes"),
        events_cache_hours=float(os.getenv("EVENTS_CACHE_HOURS", "3")),
        live_events_max=_int("LIVE_EVENTS_MAX", 12),
    )
