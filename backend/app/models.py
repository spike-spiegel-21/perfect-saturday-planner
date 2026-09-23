"""Shared shapes: mock city data, user preferences, plan options, API payloads.

The frontend mirrors the API shapes in `frontend/src/types.ts`; keep the two in sync.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

# --------------------------------------------------------------------------- vocabularies

Category = Literal[
    "music", "comedy", "movie", "theatre", "walk", "nature", "heritage", "art", "museum",
    "market", "shopping", "workshop", "gaming", "books", "sports", "food_walk",
]
CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]

Crowd = Literal["low", "medium", "high"]
VegType = Literal["pure_veg", "veg_friendly", "non_veg"]
PlaceKind = Literal["event", "activity", "restaurant"]
Energy = Literal["low", "medium", "high"]
TravelMode = Literal["walk", "auto", "cab", "metro"]

OptionKind = Literal["time_saver", "recommended", "value_for_money"]
KIND_ORDER: tuple[OptionKind, ...] = ("time_saver", "recommended", "value_for_money")
KIND_LABELS: dict[str, str] = {
    "time_saver": "Time Saver",
    "recommended": "Recommended",
    "value_for_money": "Value for Money",
}

# Tags a place may carry. Constraint checks rely on the ones marked (*).
PLACE_TAGS: frozenset[str] = frozenset({
    "low_effort", "active", "social", "quiet", "romantic", "iconic", "hidden_gem", "family",
    "seated", "late_night", "free", "live_music", "rooftop",
    "bar",                    # (*) primarily a bar/brewery -> excluded for "no alcohol"
    "wheelchair_accessible",  # (*) required when the user needs step-free access
    "jain_options",           # (*) required for jain
    "vegan_options",          # (*) required for vegan
    "cafe", "quick_bite", "street_food", "dessert", "fine_dining",  # restaurants
})

# Interest words -> event/activity categories and restaurant tags they map to.
INTEREST_MAP: dict[str, dict[str, list[str]]] = {
    "food": {"categories": ["food_walk", "market"], "restaurant_tags": ["street_food", "fine_dining", "dessert"]},
    "music": {"categories": ["music"], "restaurant_tags": ["live_music"]},
    "walk": {"categories": ["walk", "nature", "heritage"], "restaurant_tags": []},
    "nature": {"categories": ["nature", "walk"], "restaurant_tags": []},
    "movie": {"categories": ["movie"], "restaurant_tags": []},
    "film": {"categories": ["movie"], "restaurant_tags": []},
    "cinema": {"categories": ["movie"], "restaurant_tags": []},
    "art": {"categories": ["art", "museum"], "restaurant_tags": []},
    "museum": {"categories": ["museum", "heritage", "art"], "restaurant_tags": []},
    "history": {"categories": ["heritage", "museum"], "restaurant_tags": []},
    "heritage": {"categories": ["heritage", "museum"], "restaurant_tags": []},
    "comedy": {"categories": ["comedy"], "restaurant_tags": []},
    "theatre": {"categories": ["theatre"], "restaurant_tags": []},
    "theater": {"categories": ["theatre"], "restaurant_tags": []},
    "play": {"categories": ["theatre"], "restaurant_tags": []},
    "cafe": {"categories": ["books"], "restaurant_tags": ["cafe"]},
    "coffee": {"categories": [], "restaurant_tags": ["cafe"]},
    "shop": {"categories": ["shopping", "market"], "restaurant_tags": []},
    "market": {"categories": ["market", "shopping"], "restaurant_tags": ["street_food"]},
    "game": {"categories": ["gaming"], "restaurant_tags": []},
    "gaming": {"categories": ["gaming"], "restaurant_tags": []},
    "book": {"categories": ["books"], "restaurant_tags": ["cafe"]},
    "workshop": {"categories": ["workshop"], "restaurant_tags": []},
    "craft": {"categories": ["workshop"], "restaurant_tags": []},
    "pottery": {"categories": ["workshop"], "restaurant_tags": []},
    "sport": {"categories": ["sports"], "restaurant_tags": []},
    "bowling": {"categories": ["sports", "gaming"], "restaurant_tags": []},
    "dance": {"categories": ["music"], "restaurant_tags": []},
}


def interest_categories(interests: list[str]) -> set[str]:
    """Categories an interest list points at (substring match on INTEREST_MAP keys)."""
    out: set[str] = set()
    for raw in interests:
        word = raw.lower()
        for key, target in INTEREST_MAP.items():
            if key in word:
                out.update(target["categories"])
        for cat in CATEGORIES:
            if cat.replace("_", " ") in word:
                out.add(cat)
    return out


def interest_restaurant_tags(interests: list[str]) -> set[str]:
    out: set[str] = set()
    for raw in interests:
        word = raw.lower()
        for key, target in INTEREST_MAP.items():
            if key in word:
                out.update(target["restaurant_tags"])
    return out


# --------------------------------------------------------------------------- mock city data


class PriceTier(BaseModel):
    tier: str
    price: int = Field(ge=0, description="INR per person")


class CrowdBySlot(BaseModel):
    """Crowd level by time slot: morning <12:00, afternoon 12-17, evening 17-21, night >=21."""

    morning: Crowd = "low"
    afternoon: Crowd = "medium"
    evening: Crowd = "medium"
    night: Crowd = "low"


class Place(BaseModel):
    id: str
    kind: PlaceKind
    name: str
    area: str
    lat: float
    lng: float
    blurb: str
    indoor: bool
    crowd: CrowdBySlot
    tags: list[str] = []
    cheaper_alternative_ids: list[str] = []
    # events + activities
    category: Category | None = None
    start_times: list[str] = []                 # events only, "HH:MM" on Saturday
    open_hours: list[tuple[str, str]] = []      # activities + restaurants, e.g. [("06:00", "10:00")]
    duration_min: int | None = None             # events + activities (typical)
    price_tiers: list[PriceTier] = []           # events + activities; free -> [{"tier": "entry", "price": 0}]
    # restaurants
    cuisine: str | None = None
    cost_for_one: int | None = None
    veg: VegType | None = None
    meal_min: int | None = None

    @model_validator(mode="after")
    def _kind_fields(self) -> Place:
        if self.kind == "restaurant":
            missing = [f for f in ("cuisine", "cost_for_one", "veg", "meal_min") if getattr(self, f) is None]
            if not self.open_hours:
                missing.append("open_hours")
        else:
            missing = [f for f in ("category", "duration_min") if getattr(self, f) is None]
            if not self.price_tiers:
                missing.append("price_tiers")
            if self.kind == "event" and not self.start_times:
                missing.append("start_times")
            if self.kind == "activity" and not self.open_hours:
                missing.append("open_hours")
        if missing:
            raise ValueError(f"{self.id}: {self.kind} is missing {missing}")
        return self

    @property
    def base_price(self) -> int:
        """Cheapest way in: lowest ticket tier, or a restaurant's cost for one."""
        if self.kind == "restaurant":
            return self.cost_for_one or 0
        return min(t.price for t in self.price_tiers)

    @property
    def label(self) -> str:
        return (self.cuisine if self.kind == "restaurant" else self.category) or ""

    @property
    def typical_min(self) -> int:
        return (self.meal_min if self.kind == "restaurant" else self.duration_min) or 60


class Area(BaseModel):
    name: str
    lat: float
    lng: float


class Fares(BaseModel):
    auto_base: int
    auto_per_km: float
    cab_base: int
    cab_per_km: float
    metro: bool = True


class HourWeather(BaseModel):
    hour: int = Field(ge=0, le=23)
    temp_c: int
    rain_pct: int = Field(ge=0, le=100)
    aqi: int = Field(ge=0)


class WeatherDay(BaseModel):
    summary: str
    hourly: list[HourWeather]


class CityData(BaseModel):
    key: str                      # "gurgaon"
    name: str                     # "Gurgaon"
    aliases: list[str]            # lowercase spellings users type: "gurugram", "ggn", ...
    center: Area                  # default start point when the user gives no area
    areas: list[Area]             # neighbourhoods users may start from; place.area values come from here
    traffic_kmph: dict[str, float]  # average road speed by slot: morning/afternoon/evening/night
    fares: Fares
    weather: WeatherDay           # the upcoming Saturday, hours 8..23
    places: list[Place]


# --------------------------------------------------------------------------- preferences


class Rules(BaseModel):
    """Machine-checkable constraints derived from the user's free-text constraints."""

    vegetarian: bool = False
    vegan: bool = False
    jain: bool = False
    avoid_crowds: bool = False
    no_alcohol: bool = False
    wheelchair: bool = False
    end_by: str | None = None  # "HH:MM" latest time to be back


class Slots(BaseModel):
    """What intake has collected so far. None = not answered yet ([] constraints = "none")."""

    city: str | None = None          # canonical key, e.g. "gurgaon"
    city_name: str | None = None
    start_area: str | None = None
    budget_inr: int | None = None
    available_hours: float | None = None
    start_time: str | None = None    # only when the user said one
    mood: str | None = None
    energy: Energy | None = None
    interests: list[str] | None = None
    constraints: list[str] | None = None
    rules: Rules = Rules()


class Preferences(BaseModel):
    """Complete input for a planning run (built from filled Slots)."""

    city: str
    city_name: str
    start_area: str | None = None
    budget_inr: int
    available_hours: float
    start_time: str
    start_time_assumed: bool = True
    mood: str
    energy: Energy = "medium"
    interests: list[str]
    constraints: list[str] = []
    rules: Rules = Rules()


# --------------------------------------------------------------------------- plans


class PlanItemIn(BaseModel):
    """One stop as the model submits it: a reference to a tool-returned place + timing + rationale."""

    ref_id: str = Field(description="id of a place returned by search_events / search_restaurants")
    start: str = Field(description="start time HH:MM (events: one of their listed start times)")
    duration_min: int | None = Field(None, description="minutes spent here; omit to use the typical duration")
    tier: str | None = Field(None, description="ticket tier name for events with several tiers; omit for the cheapest")
    why_it_fits: str = Field(description="one sentence tying this stop to the user's own mood/interests/constraints")


class PlanOptionIn(BaseModel):
    kind: OptionKind
    title: str = Field(description="short, specific title, e.g. 'Slow evening around Cyber Hub'")
    pitch: str = Field(description="one sentence on why this option suits the user")
    items: list[PlanItemIn]
    tradeoffs: list[str] = Field(default_factory=list, description="honest compromises, e.g. over budget, crowded, weather")


class Leg(BaseModel):
    from_name: str
    to_name: str
    mode: TravelMode
    km: float
    minutes: int
    fare_inr: int


class PlanItemOut(BaseModel):
    ref_id: str
    name: str
    kind: PlaceKind
    label: str                 # category or cuisine
    area: str
    start: str
    end: str
    duration_min: int
    cost_inr: int
    tier: str | None = None
    indoor: bool
    crowd: Crowd               # at the scheduled time
    veg: VegType | None = None
    blurb: str
    why_it_fits: str
    leg_before: Leg | None = None


class Totals(BaseModel):
    cost_inr: int              # everything: tickets + food + travel
    spend_inr: int             # tickets + food
    travel_inr: int
    activity_min: int
    travel_min: int
    start: str                 # leave the start point
    end: str                   # back at the start point
    budget_inr: int
    available_min: int


class Validation(BaseModel):
    status: Literal["pass", "warn", "fail"]
    violations: list[str] = []
    warnings: list[str] = []
    adjusted: list[str] = []   # start times the validator moved to make travel work, e.g. "MAP 16:10→16:25"


class PlanOptionOut(BaseModel):
    kind: OptionKind
    title: str
    pitch: str
    items: list[PlanItemOut]
    leg_home: Leg | None = None
    tradeoffs: list[str] = []
    totals: Totals
    validation: Validation
    source: Literal["agent", "fallback"] = "agent"


# --------------------------------------------------------------------------- API payloads


class Pill(BaseModel):
    label: str                 # what the chip shows, e.g. "Vegetarian (last time)"
    value: str                 # what it inserts into the text box, e.g. "Vegetarian"
    remembered: bool = False   # came from cross-session memory


class AssistantTurn(BaseModel):
    reply: str
    asking: str | None = None  # field being asked: city|budget|available_time|mood|interests|constraints
    pills: list[Pill] = []
    multi: bool = False        # pills are multi-select
    placeholder: str = ""
    slots: Slots = Slots()
    missing: list[str] = []
    ready: bool = False        # all required fields present -> client starts POST /plan
    parse: dict | None = None  # how this turn was understood: {method: llm|rules, ms, updated[], vague[], unsupported_city}


class RunOut(BaseModel):
    run_id: str
    options: list[PlanOptionOut]          # always ordered time_saver, recommended, value_for_money
    assumptions: list[str] = []
    weather_note: str | None = None
    fallback: bool = False
    fallback_reason: str | None = None
    chosen: OptionKind | None = None
    usage: dict = {}                      # steps, tool_calls, prompt_tokens, completion_tokens, cost_usd, seconds


class MessageOut(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    turn: AssistantTurn | None = None     # assistant intake turns carry pills etc.
    run_id: str | None = None             # assistant message announcing a plan run


class SessionOut(BaseModel):
    session_id: str
    user_id: str
    status: Literal["collecting", "ready", "planning", "planned"]
    slots: Slots
    messages: list[MessageOut]
    turn: AssistantTurn | None = None     # latest assistant turn (pills/placeholder to render)
    last_run: RunOut | None = None
    last_trace: list[dict] = []
    memory_hint: str | None = None


class CreateSessionIn(BaseModel):
    user_id: str = Field(min_length=6, max_length=64)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class ChooseIn(BaseModel):
    run_id: str
    kind: OptionKind


# --------------------------------------------------------------------------- SSE trace events
#
# Every event is a JSON object with "type" plus fields, sent as `data: {...}\n\n`:
#   run_started {run_id, prefs, window: {start, end}, limits}
#   step        {n, max}
#   narration   {text}                       model's one-line "what I'm doing"
#   thinking    {text}                       short reasoning summary, if the model returned one
#   tool_call   {id, name, args}
#   tool_result {id, name, ok, summary, ms, cached, error?}
#   validation  {kind, status, totals, violations, warnings}
#   guard       {name, detail}               a loop limit tripped
#   fallback    {reason, detail}             rule-based planner filled in
#   plans       {run: RunOut}
#   usage       {steps, tool_calls, prompt_tokens, completion_tokens, cost_usd, seconds}
#   error       {message}
#   done        {}
