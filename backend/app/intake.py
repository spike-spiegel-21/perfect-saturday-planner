"""Conversational intake: turn free text into the six required fields, one question at a time.

Each user turn: extract (Sonnet 5 structured output, or a regex fallback if the model is unavailable) ->
merge into the session's slots -> ask for the next missing field with suggestion pills and a placeholder.
The agent only runs once every required field is filled.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from app.data import SUPPORTED, load_city, resolve_city
from app.llm import LLM, LLMError
from app.models import AssistantTurn, Energy, Pill, Preferences, Rules, Slots
from app.util import fmt, is_hhmm, rupees, to_min

ORDER = ("city", "budget", "available_time", "mood", "interests", "constraints")
MAX_ASKS = 3  # first ask + two re-asks, then a stated default


@dataclass(frozen=True)
class FieldSpec:
    question: str
    reask: str
    pills: tuple[str, ...]
    multi: bool
    placeholder: str


CITY_NAMES = tuple(load_city(k).name for k in SUPPORTED)

FIELDS: dict[str, FieldSpec] = {
    "city": FieldSpec(
        "Which city are you in?",
        f"Which city should I plan in? I have data for {', '.join(CITY_NAMES[:-1])} and {CITY_NAMES[-1]}.",
        CITY_NAMES, False, "e.g. Gurgaon, near Cyber Hub",
    ),
    "budget": FieldSpec(
        "What's your all-in budget for the day?",
        "Roughly how much can you spend in total, in rupees? A number helps, like ₹1,500.",
        ("₹500", "₹1,000", "₹2,000", "₹3,000", "₹5,000"), False, "e.g. ₹2000 or 3k",
    ),
    "available_time": FieldSpec(
        "How much time do you have on Saturday?",
        "How many hours can you give it? Something like 4 hours, or 3pm to 9pm.",
        ("2 hours", "4 hours", "Half day (6 hours)", "Full day", "Evening (5–10pm)"), False, "e.g. 4 hours from 3pm",
    ),
    "mood": FieldSpec(
        "How are you feeling going into Saturday?",
        "In a few words, what's your mood? Tired, social, adventurous…",
        ("Tired but want some fun", "Chill and slow", "Adventurous", "Social", "Romantic", "Need me-time"), True,
        "e.g. tired but want to do something fun",
    ),
    "interests": FieldSpec(
        "What are you into? Pick a few or type your own.",
        "Tell me a couple of things you enjoy, like food, music or walks.",
        ("Food", "Live music", "Walks", "Movies", "Art & museums", "Comedy", "Cafés", "Shopping", "Nature"), True,
        "e.g. food, live music, a quiet walk",
    ),
    "constraints": FieldSpec(
        "Anything I should keep in mind? Diet, crowds, a time to be back…",
        "Any constraints at all? Say 'none' if there aren't any.",
        ("Vegetarian", "Avoid crowds", "No alcohol", "Back by 9pm", "Wheelchair-friendly", "None"), True,
        'e.g. vegetarian, avoid crowded places, or "none"',
    ),
}

GREETING = (
    "Hey! How should we plan your Saturday? Tell me anything: where you are, your budget, "
    "how much time you have, how you're feeling."
)
GREETING_PLACEHOLDER = "e.g. I'm in Gurgaon and my budget is ₹3000"
REFINE_PILLS = ("Make it cheaper", "Less travel", "More outdoors", "Start later", "Swap dinner")
REFINE_PLACEHOLDER = "e.g. make it cheaper, or swap dinner for street food"
DEFAULTS = {"budget": 1500, "available_time": 4.0, "mood": "open to anything", "interests": ["surprise me"], "constraints": []}


# --------------------------------------------------------------------------- extraction


class Extraction(BaseModel):
    city: str | None = None
    start_area: str | None = None
    budget_inr: int | None = None
    available_hours: float | None = None
    start_time: str | None = None
    mood: str | None = None
    energy: Energy | None = None
    interests: list[str] | None = None
    constraints: list[str] | None = None
    vague_fields: list[str] = []
    refinement_note: str | None = None
    ack: str = ""


def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "city": _nullable({"type": "string"}),
        "start_area": _nullable({"type": "string"}),
        "budget_inr": _nullable({"type": "integer"}),
        "available_hours": _nullable({"type": "number"}),
        "start_time": _nullable({"type": "string"}),
        "mood": _nullable({"type": "string"}),
        "energy": _nullable({"type": "string", "enum": ["low", "medium", "high"]}),
        "interests": _nullable({"type": "array", "items": {"type": "string"}}),
        "constraints": _nullable({"type": "array", "items": {"type": "string"}}),
        "vague_fields": {"type": "array", "items": {"type": "string", "enum": list(ORDER)}},
        "refinement_note": _nullable({"type": "string"}),
        "ack": {"type": "string"},
    },
    "required": [
        "city", "start_area", "budget_inr", "available_hours", "start_time", "mood", "energy", "interests",
        "constraints", "vague_fields", "refinement_note", "ack",
    ],
}

EXTRACT_PROMPT = """\
You extract Saturday-plan preferences from ONE user message in a planning chat. Output JSON only.

The assistant's last question was about: {asking}.
Already known: {known}

Rules:
- Fill a field only if THIS message states or clearly implies it; otherwise null. Never guess.
- Short answers refer to the last question ("3" after the time question = 3 hours; "veg" after constraints).
- city: as written ("Gurugram"). start_area: a neighbourhood if mentioned ("Indiranagar").
- budget_inr: integer rupees. "3k" -> 3000, "2-3k" -> 3000, "under 1500" -> 1500. Other currencies: 1 USD ~ 85 INR.
- available_hours: a number. "half day" -> 6, "full day" -> 10, "evening" -> 5 with start_time "17:00",
  "3pm to 9pm" -> 6 with start_time "15:00". If only a start time is given, assume free until 22:00.
- start_time: "HH:MM" 24h, only if stated or implied.
- mood: the user's own words, short ("tired but wants to do something fun"). energy: low for tired/lazy/exhausted,
  high for energetic/adventurous, otherwise medium; null if no mood given.
- interests: short lowercase phrases (["food", "live music", "walks"]); "anything"/"surprise me" -> ["surprise me"].
- constraints: short phrases. Use exactly these when they apply: "vegetarian", "vegan", "jain", "avoid crowds",
  "no alcohol", "wheelchair access", "back by HH:MM". "none"/"no"/"nothing" in answer to the constraints
  question -> []. If they say anywhere that they have no constraints ("no constraints", "no restrictions",
  "anything works") -> [] as well. Otherwise null when not mentioned.
- vague_fields: fields the user tried to answer but too vaguely to use ("not too much", "some time").
- refinement_note: if they ask to change an existing plan ("make it cheaper", "more outdoors"), a short note; else null.
- ack: at most 12 words, warm and specific to what they said, no question, no emoji ("Gurgaon on ₹3,000, nice.").
  If nothing usable: a gentle "No worries." style line.
"""


async def llm_extract(llm: LLM, text: str, slots: Slots, asking: str | None) -> Extraction:
    known = {k: v for k, v in slots.model_dump(exclude={"rules", "city"}).items() if v not in (None, [])}
    if slots.available_hours and not slots.start_time:
        known["start_time"] = default_start(slots.available_hours, slots.rules.end_by) + " (assumed)"
    messages = [
        {"role": "system", "content": EXTRACT_PROMPT.format(asking=asking or "anything (opening question)", known=json.dumps(known, ensure_ascii=False))},
        {"role": "user", "content": text},
    ]
    fmt_ = {"type": "json_schema", "json_schema": {"name": "preferences", "strict": True, "schema": EXTRACT_SCHEMA}}
    try:
        res = await llm.chat(messages, response_format=fmt_, reasoning={"enabled": False}, max_tokens=1000, cache=False)
    except LLMError as exc:
        if exc.code != "bad_request":
            raise
        # schema mode refused upstream: ask for plain JSON instead
        messages[0]["content"] += "\nReturn only a JSON object with exactly these keys: " + ", ".join(EXTRACT_SCHEMA["required"])
        res = await llm.chat(messages, reasoning={"enabled": False}, max_tokens=1000, cache=False)
    raw = res.text
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        return Extraction.model_validate(json.loads(match.group(0) if match else raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError(f"unparseable extraction: {exc}", "empty") from exc


_MONEY = re.compile(r"(?:₹|rs\.?|inr|rupees?)\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?|(\d[\d,]*(?:\.\d+)?)\s*(k|rupees|rs|inr)\b", re.I)
_HOURS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b", re.I)
_CLOCK = r"(?<![\d₹,.])(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?![\d,])"
_RANGE = re.compile(_CLOCK + r"\s*(?:-|–|to|till|until)\s*" + _CLOCK, re.I)
_FROM = re.compile(r"(?:from|after|at|starting)\s+" + _CLOCK, re.I)
_NONE = re.compile(r"^\s*(none|no|nope|nothing|nah|no constraints|nothing really|all good|na)\s*[.!]?\s*$", re.I)
_NO_CONSTRAINTS = re.compile(r"\bno (constraints|restrictions|dietary restrictions|preferences)\b|\bnothing to avoid\b", re.I)
_REFINE = re.compile(r"\b(cheaper|less travel|more (?:outdoors?|indoors?)|start later|later start|earlier|swap|shorter|longer|different|change|instead|less walking)\b", re.I)
_MOOD_WORDS = re.compile(r"\b(tired|exhausted|sleepy|lazy|bored|stressed|chill|relaxed|happy|excited|adventurous|energetic|social|romantic|low|meh)\b", re.I)


def _clock(h: str, m: str | None, ampm: str | None, *, assume_pm: bool = True) -> int:
    hour, minute = int(h), int(m or 0)
    if ampm:
        hour = hour % 12 + (12 if ampm.lower() == "pm" else 0)
    elif assume_pm and 1 <= hour <= 11:
        hour += 12
    return hour * 60 + minute


def regex_extract(text: str, asking: str | None) -> Extraction:
    """Fallback extractor when the model is unavailable: handles the common, well-formed answers."""
    t = text.strip()
    low = t.lower()
    ex = Extraction(ack="Got it.")
    city = resolve_city(low)
    if city:
        ex.city = city.name
    elif asking == "city" and len(t) <= 40 and re.fullmatch(r"[A-Za-z .'-]+", t):
        ex.city = t.title()
    if m := _MONEY.search(t):
        num = float((m.group(1) or m.group(3)).replace(",", ""))
        ex.budget_inr = int(num * 1000 if (m.group(2) or (m.group(4) or "").lower() == "k") else num)
    elif asking == "budget" and (m := re.search(r"\b(\d{3,6})\b", t)):
        ex.budget_inr = int(m.group(1))
    if m := _RANGE.search(t):
        start = _clock(m.group(1), m.group(2), m.group(3) or m.group(6))
        end = _clock(m.group(4), m.group(5), m.group(6))
        if end > start:
            ex.start_time, ex.available_hours = fmt(start), round((end - start) / 60, 1)
    if ex.available_hours is None:
        if m := _HOURS.search(t):
            ex.available_hours = float(m.group(1))
        elif "half day" in low or "half-day" in low:
            ex.available_hours = 6
        elif "full day" in low or "whole day" in low:
            ex.available_hours = 10
        elif "evening" in low and asking == "available_time":
            ex.available_hours, ex.start_time = 5, "17:00"
        elif asking == "available_time" and (m := re.fullmatch(r"\s*(\d{1,2}(?:\.\d)?)\s*", t)):
            ex.available_hours = float(m.group(1))
    if ex.start_time is None and (m := _FROM.search(t)):
        ex.start_time = fmt(_clock(m.group(1), m.group(2), m.group(3)))
        if ex.available_hours is None:
            ex.available_hours = max(1.0, round((22 * 60 - to_min(ex.start_time)) / 60, 1))
    if asking == "mood" and t:
        ex.mood = t[:120]
    elif m := _MOOD_WORDS.search(t):
        ex.mood = m.group(1).lower()
    if ex.mood:
        ex.energy = "low" if re.search(r"tired|exhausted|sleepy|lazy|low|meh", ex.mood, re.I) else (
            "high" if re.search(r"adventur|energetic|excited", ex.mood, re.I) else "medium")
    if asking == "interests" and t:
        ex.interests = [p.strip().lower() for p in re.split(r",|\band\b|/|\+", t) if p.strip()][:8]
    else:
        found = [k for k in ("food", "music", "walk", "movie", "comedy", "art", "museum", "cafe", "shopping", "nature", "theatre", "gaming") if k in low]
        if found:
            ex.interests = found
    if asking is None and _REFINE.search(t):
        ex.refinement_note = t[:120]
    if (asking == "constraints" and _NONE.match(t)) or _NO_CONSTRAINTS.search(t):
        ex.constraints = []
    elif asking == "constraints" and t:
        ex.constraints = [p.strip().lower() for p in re.split(r",|\band\b|/", t) if p.strip()][:8]
    else:
        cons = []
        if re.search(r"(?<!non-)(?<!non )\bveg(etarian|gie)?\b", low):
            cons.append("vegetarian")
        if "crowd" in low:
            cons.append("avoid crowds")
        if "alcohol" in low:
            cons.append("no alcohol")
        if cons:
            ex.constraints = cons
    return ex


def rules_from(constraints: list[str]) -> Rules:
    """Machine-checkable flags from the canonical constraint phrases (deterministic, no model)."""
    text = " | ".join(c.lower() for c in constraints)
    vegan = "vegan" in text
    jain = "jain" in text
    veg = vegan or jain or bool(re.search(r"(?<!non-)(?<!non )\bveg(etarian|gie|gy|an)?\b|no meat|pure veg", text))
    end_by = None
    if m := re.search(r"(?:back|home|done|finish|end)\w*\s+(?:by|before)\s+" + _CLOCK, text):
        end_by = fmt(_clock(m.group(1), m.group(2), m.group(3)))
    return Rules(
        vegetarian=veg, vegan=vegan, jain=jain,
        avoid_crowds=bool(re.search(r"crowd|busy|packed|rush|quiet place", text)),
        no_alcohol=bool(re.search(r"alcohol|\bdrink|sober|teetotal|\bbars?\b", text)),
        wheelchair=bool(re.search(r"wheelchair|accessib|step.?free|mobility", text)),
        end_by=end_by,
    )


# --------------------------------------------------------------------------- merging + questions


@dataclass
class TurnState:
    """Per-session intake bookkeeping, stored as JSON on the session row."""

    asked: dict[str, int] = field(default_factory=dict)
    last_asked: str | None = None
    assumed: list[str] = field(default_factory=list)
    refinement: str | None = None

    @classmethod
    def load(cls, d: dict) -> TurnState:
        return cls(asked=d.get("asked", {}), last_asked=d.get("last_asked"), assumed=d.get("assumed", []),
                   refinement=d.get("refinement"))

    def dump(self) -> dict:
        return {"asked": self.asked, "last_asked": self.last_asked, "assumed": self.assumed, "refinement": self.refinement}


def filled(slots: Slots, name: str) -> bool:
    return {
        "city": slots.city is not None,
        "budget": slots.budget_inr is not None,
        "available_time": slots.available_hours is not None,
        "mood": bool(slots.mood),
        "interests": bool(slots.interests),
        "constraints": slots.constraints is not None,
    }[name]


def missing_fields(slots: Slots) -> list[str]:
    return [f for f in ORDER if not filled(slots, f)]


@dataclass
class Merge:
    slots: Slots
    changed: set[str]
    vague: set[str]
    unsupported_city: str | None = None


def merge(slots: Slots, ex: Extraction, asking: str | None) -> Merge:
    s = slots.model_copy(deep=True)
    changed: set[str] = set()
    vague = {v for v in ex.vague_fields if v in ORDER}
    unsupported = None

    def put(name: str, attr: str, value) -> None:
        if getattr(s, attr) != value:
            setattr(s, attr, value)
            changed.add(name)

    if ex.city:
        city = resolve_city(ex.city)
        if city:
            put("city", "city", city.key)
            s.city_name = city.name
        else:
            unsupported = ex.city.strip()[:40]
    if ex.start_area:
        s.start_area = ex.start_area.strip()[:60]
    if ex.budget_inr is not None:
        if 100 <= ex.budget_inr <= 50_000:
            put("budget", "budget_inr", int(ex.budget_inr))
        else:
            vague.add("budget")
    if ex.available_hours is not None:
        if 0.5 <= ex.available_hours <= 14:
            put("available_time", "available_hours", round(float(ex.available_hours) * 2) / 2)
        else:
            vague.add("available_time")
    if ex.start_time and is_hhmm(ex.start_time):
        put("available_time", "start_time", ex.start_time)
    if ex.mood and ex.mood.strip():
        put("mood", "mood", ex.mood.strip()[:120])
        s.energy = ex.energy or s.energy or "medium"
    if ex.interests:
        merged = _union(s.interests or [], ex.interests)
        if "surprise me" in merged and len(merged) > 1:
            merged.remove("surprise me")
        put("interests", "interests", merged[:8])
    if ex.constraints is not None:  # [] means the user said "none", whether or not we asked yet
        cleaned = [c for c in ex.constraints if c.strip().lower() not in {"none", "no", "nothing"}]
        put("constraints", "constraints", _union(s.constraints or [], cleaned))
        s.rules = rules_from(s.constraints or [])
    return Merge(s, changed, vague - {n for n in changed}, unsupported)


def _union(old: list[str], new: list[str]) -> list[str]:
    out = list(old)
    for item in new:
        item = item.strip()
        if item and item.lower() not in {o.lower() for o in out}:
            out.append(item)
    return out


def apply_default(slots: Slots, name: str, state: TurnState) -> None:
    if name == "budget":
        slots.budget_inr = DEFAULTS["budget"]
        state.assumed.append(f"You didn't pin down a budget, so I assumed {rupees(DEFAULTS['budget'])}.")
    elif name == "available_time":
        slots.available_hours = DEFAULTS["available_time"]
        state.assumed.append("You didn't say how long, so I planned for about 4 hours.")
    elif name == "mood":
        slots.mood, slots.energy = DEFAULTS["mood"], "medium"
    elif name == "interests":
        slots.interests = list(DEFAULTS["interests"])
        state.assumed.append("No interests given, so I mixed a few popular things.")
    elif name == "constraints":
        slots.constraints = []


def pills_for(name: str, profile: dict | None) -> list[Pill]:
    spec = FIELDS[name]
    base = [Pill(label=p, value=p) for p in spec.pills]
    remembered: list[Pill] = []
    if profile:
        if name == "city" and profile.get("home_city_name"):
            remembered.append(Pill(label=f"{profile['home_city_name']} (last time)", value=profile["home_city_name"], remembered=True))
        elif name == "budget" and profile.get("last_budget"):
            remembered.append(Pill(label=f"{rupees(profile['last_budget'])} (last time)", value=rupees(profile["last_budget"]), remembered=True))
        elif name == "available_time" and profile.get("last_hours"):
            hours = f"{profile['last_hours']:g} hours"
            remembered.append(Pill(label=f"{hours} (last time)", value=hours, remembered=True))
        elif name == "interests":
            top = sorted(profile.get("interest_counts", {}).items(), key=lambda kv: -kv[1])[:3]
            remembered += [Pill(label=f"{k.title()} (last time)", value=k.title(), remembered=True) for k, _ in top]
        elif name == "constraints":
            remembered += [Pill(label=f"{c.title()} (last time)", value=c.title(), remembered=True) for c in profile.get("constraints", [])]
    taken = {p.value.lower() for p in remembered}
    return remembered + [p for p in base if p.value.lower() not in taken]


def greeting(profile: dict | None) -> tuple[AssistantTurn, str | None]:
    hint = None
    reply = GREETING
    if profile and profile.get("home_city_name"):
        bits = [profile["home_city_name"], rupees(profile.get("last_budget", 0))] + list(profile.get("constraints", []))
        hint = "Last time: " + " · ".join(bits)
        reply = f"Welcome back! {hint}. How should we plan this Saturday? Tell me anything."
    return AssistantTurn(reply=reply, placeholder=GREETING_PLACEHOLDER, missing=list(ORDER)), hint


@dataclass
class TurnResult:
    turn: AssistantTurn
    slots: Slots
    state: TurnState
    replan: bool = False          # status was "planned" and something changed -> run again
    parse: dict = field(default_factory=dict)


async def handle_turn(
    llm: LLM, text: str, slots: Slots, state: TurnState, *, status: str, profile: dict | None
) -> TurnResult:
    res = await _handle_turn(llm, text, slots, state, status=status, profile=profile)
    res.turn.parse = res.parse
    return res


async def _handle_turn(
    llm: LLM, text: str, slots: Slots, state: TurnState, *, status: str, profile: dict | None
) -> TurnResult:
    asking = state.last_asked if status == "collecting" else None
    started = time.perf_counter()
    method = "llm"
    try:
        ex = await llm_extract(llm, text, slots, asking)
    except LLMError:
        ex, method = regex_extract(text, asking), "rules"
    m = merge(slots, ex, asking)
    s = m.slots
    parse = {
        "method": method, "ms": int((time.perf_counter() - started) * 1000), "updated": sorted(m.changed),
        "vague": sorted(m.vague), "unsupported_city": m.unsupported_city,
    }
    ack = _ack(ex.ack, method)

    if status in {"planned", "ready", "planning"}:
        if m.changed or ex.refinement_note:
            state.refinement = ex.refinement_note or ("updated " + ", ".join(sorted(m.changed)))
            reply = f"{ack} Re-planning with that…".strip()
            return TurnResult(_turn(reply, s, ready=True), s, state, replan=True, parse=parse)
        reply = ex.ack if method == "llm" and ex.ack else "Anything you'd like to change?"
        turn = _turn(reply + " I can make it cheaper, shorter, or more indoor or outdoor.", s)
        turn.pills = [Pill(label=p, value=p) for p in REFINE_PILLS]
        turn.placeholder = REFINE_PLACEHOLDER
        return TurnResult(turn, s, state, parse=parse)

    if m.unsupported_city:
        names = ", ".join(CITY_NAMES[:-1]) + f" and {CITY_NAMES[-1]}"
        reply = f"I don't have data for {m.unsupported_city} yet. I can plan in {names}. Which one works?"
        state.last_asked = "city"
        state.asked["city"] = state.asked.get("city", 0) + 1
        turn = _turn(reply, s, asking="city", pills=pills_for("city", profile), multi=False,
                     placeholder=FIELDS["city"].placeholder)
        return TurnResult(turn, s, state, parse=parse)

    while True:
        missing = missing_fields(s)
        if not missing:
            state.last_asked = None
            reply = f"{ack} Got everything, planning your Saturday now…".strip()
            return TurnResult(_turn(reply, s, ready=True), s, state, parse=parse)
        name = missing[0]
        if state.asked.get(name, 0) >= MAX_ASKS and name != "city":
            apply_default(s, name, state)
            continue
        break

    spec = FIELDS[name]
    reask = state.last_asked == name or name in m.vague
    question = spec.reask if reask else spec.question
    state.last_asked = name
    state.asked[name] = state.asked.get(name, 0) + 1
    reply = f"{ack} {question}".strip() if m.changed else question
    turn = _turn(reply, s, asking=name, pills=pills_for(name, profile), multi=spec.multi, placeholder=spec.placeholder)
    return TurnResult(turn, s, state, parse=parse)


def _ack(ack: str, method: str) -> str:
    ack = (ack or "").strip()
    if method != "llm":
        return "Got it."
    words = ack.split()
    return " ".join(words[:14]) if words else ""


def _turn(reply: str, s: Slots, *, asking: str | None = None, pills: list[Pill] | None = None, multi: bool = False,
          placeholder: str = "", ready: bool = False) -> AssistantTurn:
    return AssistantTurn(reply=reply, asking=asking, pills=pills or [], multi=multi, placeholder=placeholder,
                         slots=s, missing=missing_fields(s), ready=ready)


def default_start(hours: float, end_by: str | None) -> str:
    if hours >= 9:
        start = 10 * 60
    elif hours >= 6:
        start = min(14 * 60, int(22.5 * 60 - hours * 60))
    elif hours >= 3:
        start = 16 * 60
    else:
        start = 17 * 60
    if end_by and is_hhmm(end_by):
        start = min(start, to_min(end_by) - int(hours * 60))
    return fmt(max(8 * 60, start))


def to_preferences(s: Slots) -> Preferences:
    hours = s.available_hours or 4.0
    return Preferences(
        city=s.city or "", city_name=s.city_name or "", start_area=s.start_area, budget_inr=s.budget_inr or 1500,
        available_hours=hours, start_time=s.start_time or default_start(hours, s.rules.end_by),
        start_time_assumed=s.start_time is None, mood=s.mood or "open to anything", energy=s.energy or "medium",
        interests=s.interests or ["surprise me"], constraints=s.constraints or [], rules=s.rules,
    )

