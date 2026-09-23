"""Tool plumbing: the per-run context, tool definitions the model sees, and a guarded dispatcher."""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ValidationError

from app.config import Limits
from app.data import place_index
from app.llm import ToolCall
from app.models import Area, CityData, Place, PlanOptionOut, Preferences
from app.util import fmt, next_saturday, to_min

Emit = Callable[[dict], Awaitable[None]]


class ToolUnavailable(Exception):
    """A (mock) upstream service is down; the model gets a structured error and adapts."""


@dataclass
class RunContext:
    prefs: Preferences
    city: CityData
    places: dict[str, Place]
    window_start: int
    window_end: int
    start_point: Area
    saturday: date
    limits: Limits
    emit: Emit
    simulate: frozenset[str] = frozenset()
    past_place_ids: frozenset[str] = frozenset()
    mock_latency_s: float = 0.0
    assumptions: list[str] = field(default_factory=list)
    # working memory for this run
    seen_ids: set[str] = field(default_factory=set)
    counts: Counter = field(default_factory=Counter)
    total_calls: int = 0
    cache: dict[str, dict] = field(default_factory=dict)
    weather_summary: str | None = None
    submit_attempts: int = 0
    drafts: dict[str, Any] = field(default_factory=dict)          # latest validated draft per kind (PlanOptionIn)
    best: dict[str, PlanOptionOut] = field(default_factory=dict)  # valid options from submissions so far
    accepted: bool = False
    submitted_assumptions: list[str] = field(default_factory=list)
    submitted_weather_note: str | None = None


def make_context(
    prefs: Preferences,
    city: CityData,
    *,
    limits: Limits,
    emit: Emit,
    simulate: frozenset[str] = frozenset(),
    past_place_ids: frozenset[str] = frozenset(),
    mock_latency_s: float = 0.0,
    today: date | None = None,
) -> RunContext:
    start = to_min(prefs.start_time)
    end = min(start + round(prefs.available_hours * 60), 23 * 60 + 45)
    assumptions: list[str] = []
    if prefs.start_time_assumed:
        assumptions.append(f"You didn't give a start time, so I assumed {fmt(start)}–{fmt(end)}.")
    if end < start + round(prefs.available_hours * 60):
        assumptions.append(f"Capped the day at {fmt(end)} (late-night options are thin).")
    point = _match_area(city, prefs.start_area)
    if point is None:
        point = city.center
        assumptions.append(f"Starting from {city.center.name} (no neighbourhood given); travel is counted from there and back.")
    return RunContext(
        prefs=prefs, city=city, places=place_index(city), window_start=start, window_end=end,
        start_point=point, saturday=next_saturday(today), limits=limits, emit=emit, simulate=simulate,
        past_place_ids=past_place_ids, mock_latency_s=mock_latency_s, assumptions=assumptions,
    )


def _match_area(city: CityData, text: str | None) -> Area | None:
    if not text:
        return None
    t = text.lower()
    for area in city.areas:
        if area.name.lower() in t or t in area.name.lower():
            return area
    return None


# --------------------------------------------------------------------------- tool definitions


@dataclass
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    handler: Callable[[RunContext, Any], Awaitable[dict]]
    summarize: Callable[[dict], str]

    def spec(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": inline_schema(self.args)},
        }


def inline_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema with $refs inlined and titles dropped: smaller and friendlier for the model."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].split("/")[-1]])
            return {k: walk(v) for k, v in node.items() if k != "title"}
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(schema)


# --------------------------------------------------------------------------- dispatcher


def _args_key(name: str, args: dict) -> str:
    return name + ":" + json.dumps(args, sort_keys=True, separators=(",", ":"))


def trace_args(name: str, args: dict) -> dict:
    """Compact args for the trace panel (plans are summarised, not dumped)."""
    if name in {"validate_plan", "submit_plans"}:
        opts = args.get("options") or []
        return {"options": [
            {"kind": o.get("kind"), "stops": [i.get("ref_id") for i in o.get("items", [])]} for o in opts if isinstance(o, dict)
        ]}
    return args


async def dispatch(ctx: RunContext, tools: dict[str, Tool], call: ToolCall) -> dict:
    """Run one tool call under the guards. Always returns a JSON-able result (errors included)."""
    started = time.perf_counter()
    try:
        args = json.loads(call.arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("arguments must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        args = {}
        result: dict = {"error": f"invalid arguments JSON: {exc}"}
        await _emit_result(ctx, call, result, started, cached=False)
        return result

    await ctx.emit({"type": "tool_call", "id": call.id, "name": call.name, "args": trace_args(call.name, args)})

    tool = tools.get(call.name)
    if tool is None:
        result = {"error": f"unknown tool {call.name!r}; available: {sorted(tools)}"}
        await _emit_result(ctx, call, result, started, cached=False)
        return result

    key = _args_key(call.name, args)
    if key in ctx.cache and call.name != "submit_plans":
        result = {**ctx.cache[key], "note": "duplicate call: same result as before, use it instead of calling again"}
        await _emit_result(ctx, call, result, started, cached=True, summary=tool.summarize(ctx.cache[key]))
        return result

    cap = ctx.limits.caps.get(call.name, 5)
    if ctx.counts[call.name] >= cap:
        result = {"error": f"{call.name} limit reached ({cap} calls this run). Work with the results you already have."}
        await ctx.emit({"type": "guard", "name": "tool_cap", "detail": f"{call.name} capped at {cap}"})
        await _emit_result(ctx, call, result, started, cached=False)
        return result

    ctx.counts[call.name] += 1
    ctx.total_calls += 1
    try:
        parsed = tool.args.model_validate(args)
    except ValidationError as exc:
        result = {"error": "invalid arguments", "details": _short_errors(exc)}
        await _emit_result(ctx, call, result, started, cached=False)
        return result

    try:
        if ctx.mock_latency_s and call.name not in {"validate_plan", "submit_plans"}:
            await asyncio.sleep(ctx.mock_latency_s)
        result = await asyncio.wait_for(tool.handler(ctx, parsed), timeout=ctx.limits.tool_timeout_s)
    except ToolUnavailable as exc:
        result = {"error": str(exc), "hint": "the service is down; continue without it and mention it in tradeoffs"}
    except asyncio.TimeoutError:
        result = {"error": f"{call.name} timed out", "hint": "continue without it"}
    except Exception as exc:  # a tool bug must not kill the run
        result = {"error": f"{call.name} failed: {exc.__class__.__name__}: {exc}"}

    if "error" not in result:
        ctx.cache[key] = result
    await _emit_result(ctx, call, result, started, cached=False, summary=None if "error" in result else tool.summarize(result))
    return result


def _short_errors(exc: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8]]


async def _emit_result(
    ctx: RunContext, call: ToolCall, result: dict, started: float, *, cached: bool, summary: str | None = None
) -> None:
    ok = "error" not in result
    await ctx.emit({
        "type": "tool_result",
        "id": call.id,
        "name": call.name,
        "ok": ok,
        "summary": summary if ok else result.get("error", "error"),
        "ms": int((time.perf_counter() - started) * 1000),
        "cached": cached,
        **({} if ok else {"error": result.get("error")}),
    })
