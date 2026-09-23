"""Execution loop: run the model through tool steps until submit_plans accepts three valid options.

Every exit path is bounded (steps, tool calls, per-tool caps, submit attempts, wall clock) and every failure
path ends in the rule-based fallback, so a run always finishes with something to show.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from app.agent.fallback import build_fallback
from app.agent.prompts import NUDGE, SYSTEM_PROMPT, WRAP_UP, brief
from app.config import Limits
from app.llm import LLM, LLMError
from app.models import KIND_ORDER, CityData, PlanOptionOut, Preferences, RunOut
from app.tools import build_tools
from app.tools.registry import Emit, dispatch, make_context
from app.util import fmt

FALLBACK_REASONS = {
    "llm_unavailable": "the AI planner is unavailable",
    "llm_timeout": "the model took too long to answer",
    "deadline": "planning hit its time limit",
    "max_steps": "the agent hit its step limit",
    "tool_budget": "the agent hit its tool-call limit",
    "submit_retries": "the agent's plans kept failing validation",
    "no_submit": "the agent stopped without submitting plans",
}


@dataclass
class RunResult:
    run: RunOut
    trace: list[dict] = field(default_factory=list)


async def run_agent(
    prefs: Preferences,
    city: CityData,
    llm: LLM,
    emit: Emit,
    *,
    run_id: str,
    limits: Limits,
    effort: str = "low",
    memory_summary: list[str] | None = None,
    past_place_ids: frozenset[str] = frozenset(),
    refinement: str | None = None,
    previous: list[dict] | None = None,
    simulate: frozenset[str] = frozenset(),
    mock_latency_s: float = 0.0,
    extra_assumptions: list[str] | None = None,
    data_sources: dict | None = None,
) -> RunResult:
    trace: list[dict] = []
    started = time.monotonic()

    async def record(event: dict) -> None:
        event = {**event, "t": round(time.monotonic() - started, 2)}
        trace.append(event)
        await emit(event)

    ctx = make_context(
        prefs, city, limits=limits, emit=record, simulate=simulate, past_place_ids=past_place_ids,
        mock_latency_s=mock_latency_s,
    )
    ctx.assumptions[:0] = extra_assumptions or []
    tools = build_tools()
    specs = [t.spec() for t in tools.values()]
    usage = {"steps": 0, "tool_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0,
             "cost_usd": 0.0, "seconds": 0.0}
    await record({
        "type": "run_started", "run_id": run_id, "model": llm.model,
        "prefs": prefs.model_dump(), "window": {"start": fmt(ctx.window_start), "end": fmt(ctx.window_end)},
        "limits": {"max_steps": limits.max_steps, "max_tool_calls": limits.max_tool_calls, "caps": limits.caps},
        "sources": data_sources or {"events": "mock", "places": "mock"},
    })

    reason: str | None = None
    detail: str | None = None
    if "llm_down" in simulate:
        reason, detail = "llm_unavailable", "simulated outage"
    else:
        messages: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": brief(ctx, memory_summary=memory_summary or [], refinement=refinement, previous=previous)},
        ]
        nudged = False
        for step in range(1, limits.max_steps + 1):
            if time.monotonic() - started > limits.run_deadline_s:
                reason = "deadline"
                break
            usage["steps"] = step
            await record({"type": "step", "n": step, "max": limits.max_steps})
            try:
                res = await asyncio.wait_for(
                    llm.chat(messages, tools=specs, reasoning={"effort": effort}, max_tokens=limits.max_tokens),
                    timeout=limits.llm_timeout_s + 5,
                )
            except LLMError as exc:
                reason, detail = "llm_unavailable", str(exc)
                break
            except asyncio.TimeoutError:
                reason = "llm_timeout"
                break
            for k in ("prompt_tokens", "completion_tokens", "cached_tokens", "cost_usd"):
                usage[k] += res.usage.get(k, 0)
            messages.append(res.message)  # verbatim: keeps reasoning_details for the next turn
            if res.reasoning:
                await record({"type": "thinking", "text": _clip(res.reasoning, 600)})
            if res.text:
                await record({"type": "narration", "text": _clip(res.text, 400)})

            if not res.tool_calls:
                if nudged:
                    reason = "no_submit"
                    break
                nudged = True
                await record({"type": "guard", "name": "nudge", "detail": "model answered without tools; asked it to submit"})
                messages.append({"role": "user", "content": NUDGE})
                continue

            results = await asyncio.gather(*(dispatch(ctx, tools, tc) for tc in res.tool_calls))
            for tc, result in zip(res.tool_calls, results):
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, ensure_ascii=False)})
            usage["tool_calls"] = ctx.total_calls

            if ctx.accepted:  # DONE CHECK: submit_plans accepted three valid options
                break
            if ctx.submit_attempts >= limits.caps.get("submit_plans", 3):
                reason = "submit_retries"
                break
            if ctx.total_calls >= limits.max_tool_calls:
                reason = "tool_budget"
                break
            if step == limits.max_steps - 2:  # warn before the cap instead of just hitting it
                await record({"type": "guard", "name": "wrap_up", "detail": "two turns left; asked the model to submit"})
                messages.append({"role": "user", "content": WRAP_UP})
        else:
            reason = "max_steps"

    options: dict[str, PlanOptionOut]
    if ctx.accepted:
        options = dict(ctx.best)
    else:
        if reason not in {"llm_unavailable", "llm_timeout"}:
            await record({"type": "guard", "name": reason, "detail": FALLBACK_REASONS.get(reason, reason)})
        fill = build_fallback(ctx, taken=ctx.best)
        options = {**fill, **ctx.best}  # the agent's valid options win; the rules fill the gaps
        await record({
            "type": "fallback", "reason": reason,
            "detail": FALLBACK_REASONS.get(reason, reason) + (f" ({detail})" if detail else ""),
            "kept_from_agent": sorted(ctx.best), "filled": sorted(fill),
        })

    usage["seconds"] = round(time.monotonic() - started, 1)
    usage["cost_usd"] = round(usage["cost_usd"], 5)
    weather_note = ctx.submitted_weather_note or ctx.weather_summary or city.weather.summary
    if "weather_down" in simulate:
        weather_note = "Weather service was unavailable, so indoor-friendly picks were favoured."
    run = RunOut(
        run_id=run_id,
        options=[options[k] for k in KIND_ORDER if k in options],
        assumptions=_dedupe(ctx.assumptions + ctx.submitted_assumptions),
        weather_note=weather_note,
        fallback=not ctx.accepted,
        fallback_reason=None if ctx.accepted else FALLBACK_REASONS.get(reason or "", reason),
        usage=usage,
        data_sources=data_sources or {"events": "mock", "places": "mock"},
    )
    await record({"type": "usage", **usage})
    await record({"type": "plans", "run": run.model_dump()})
    return RunResult(run=run, trace=trace)


def _clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _dedupe(items: list[str]) -> list[str]:
    seen, out = set(), []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out
