"""Test doubles: a scripted LLM and helpers that build valid plans from the mock data."""

from __future__ import annotations

import json
from typing import Callable

from app.agent.fallback import build_fallback
from app.config import Limits
from app.data import load_city
from app.llm import LLMError, LLMResult, ToolCall
from app.models import KIND_ORDER, Preferences, Rules
from app.tools.registry import make_context


class FakeLLM:
    """Replays a script. Each step is an LLMResult, an Exception to raise, or fn(messages, kwargs) -> either."""

    model = "fake-model"

    def __init__(self, script: list | None = None, *, repeat_last: bool = False):
        self.script = list(script or [])
        self.repeat_last = repeat_last
        self.calls: list[tuple[list[dict], dict]] = []

    async def chat(self, messages, **kwargs) -> LLMResult:
        self.calls.append((json.loads(json.dumps(messages)), kwargs))
        if not self.script:
            raise LLMError("script exhausted", "unavailable")
        step = self.script[0] if (self.repeat_last and len(self.script) == 1) else self.script.pop(0)
        if callable(step) and not isinstance(step, LLMResult):
            step = step(messages, kwargs)
        if isinstance(step, Exception):
            raise step
        return step


def tool_step(*calls: tuple[str, dict], text: str = "") -> LLMResult:
    tcs = [ToolCall(f"call_{i}_{name}", name, json.dumps(args)) for i, (name, args) in enumerate(calls)]
    message = {
        "role": "assistant",
        **({"content": text} if text else {}),
        "tool_calls": [{"id": t.id, "type": "function", "function": {"name": t.name, "arguments": t.arguments}} for t in tcs],
    }
    return LLMResult(text=text, tool_calls=tcs, message=message,
                     usage={"prompt_tokens": 1000, "completion_tokens": 200, "cached_tokens": 0, "cost_usd": 0.004})


def text_step(text: str) -> LLMResult:
    return LLMResult(text=text, tool_calls=[], message={"role": "assistant", "content": text}, usage={})


def json_step(obj: dict) -> LLMResult:
    """An intake extraction reply (structured output)."""
    return text_step(json.dumps(obj))


def extraction(**fields) -> dict:
    base = {k: None for k in ("city", "start_area", "budget_inr", "available_hours", "start_time", "mood", "energy",
                              "interests", "constraints", "refinement_note")}
    base.update({"vague_fields": [], "ack": "Got it."})
    base.update(fields)
    return base


def prefs(**overrides) -> Preferences:
    base = dict(
        city="bangalore", city_name="Bangalore", budget_inr=2000, available_hours=4, start_time="16:00",
        start_time_assumed=True, mood="tired but wants to do something fun", energy="low",
        interests=["food", "music", "walks"], constraints=["vegetarian", "avoid crowds"],
        rules=Rules(vegetarian=True, avoid_crowds=True),
    )
    base.update(overrides)
    return Preferences(**base)


async def _noop(_event):
    return None


def ctx_for(p: Preferences, **kwargs):
    limits = kwargs.pop("limits", Limits())
    return make_context(p, load_city(p.city), limits=limits, emit=kwargs.pop("emit", _noop), **kwargs)


def seen_ids(messages: list[dict]) -> set[str]:
    """Every place id the tools returned so far in this conversation."""
    ids: set[str] = set()
    for m in messages:
        if m.get("role") != "tool":
            continue
        body = json.loads(m["content"])
        for r in body.get("results", []):
            if "id" not in r:  # validate_plan results are per-option feedback, not places
                continue
            ids.add(r["id"])
            ids.update(a["id"] for a in r.get("cheaper_alternatives", []))
    return ids


def options_from_seen(p: Preferences, allowed: set[str]) -> list[dict]:
    """Three valid option payloads (as the model would send them) using only already-seen places."""
    city = load_city(p.city)
    narrowed = city.model_copy(update={"places": [pl for pl in city.places if pl.id in allowed]})
    ctx = make_context(p, narrowed, limits=Limits(), emit=_noop)
    built = build_fallback(ctx)
    out = []
    for kind in KIND_ORDER:
        o = built[kind]
        out.append({
            "kind": kind, "title": o.title, "pitch": o.pitch, "tradeoffs": o.tradeoffs,
            "items": [{"ref_id": i.ref_id, "start": i.start, "duration_min": i.duration_min, "why_it_fits": i.why_it_fits}
                      for i in o.items],
        })
    return out


def plan_step(tool: str, p: Preferences) -> Callable:
    """A step that validates or submits plans built from whatever the searches returned."""

    def step(messages, _kwargs):
        opts = options_from_seen(p, seen_ids(messages))
        return tool_step((tool, {"options": opts} if tool == "validate_plan" else {"options": opts, "assumptions": []}),
                         text="Checking the three drafts against your budget and time.")

    return step
