"""validate_plan + submit_plans: recompute every number from place ids and check the plan against reality.

The model's arithmetic is never trusted: cost, durations, travel legs and totals are rebuilt here.
submit_plans is the loop's done signal; it only accepts three options that pass these checks.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.models import (
    KIND_LABELS, KIND_ORDER, Leg, PlanItemIn, PlanItemOut, PlanOptionIn, PlanOptionOut, Totals, Validation,
    interest_categories, interest_restaurant_tags,
)
from app.tools import travel
from app.tools.places import rule_violation
from app.tools.weather import bad_reason, hour_weather, is_bad
from app.util import fmt, is_hhmm, rupees, slot_of, to_min

OVER_BUDGET_OK = 1.10          # recommended may stretch to 110% if a trade-off says so
MIN_FILL = 0.35                # stops should cover at least this share of a 2h+ window
TRAVEL_SLACK_MIN = 5
WINDOW_GRACE_MIN = 15

_BUDGET_WORDS = re.compile(r"budget|₹|rs\.?|rupee|over|stretch|pricier|expensive|cost|splurge", re.I)
_WEATHER_WORDS = re.compile(r"rain|weather|umbrella|wet|shower|aqi|air|smog|heat|hot|sun|humid", re.I)
_SHORT_WORDS = re.compile(r"short|brief|quick|light|single stop|one stop|only one|budget|rain|nothing else fits", re.I)


def evaluate(ctx, opt: PlanOptionIn, *, grounded: bool = True, source: str = "agent") -> PlanOptionOut:
    """Rebuild one option from the mock data and list its violations (fail) and warnings (ok, but say so)."""
    prefs, rules = ctx.prefs, ctx.prefs.rules
    violations: list[str] = []
    warnings: list[str] = []

    if not 1 <= len(opt.items) <= 5:
        violations.append(f"use 1–5 stops (got {len(opt.items)})")

    resolved: list[tuple[PlanItemIn, object, int, int]] = []  # (item, place, start, duration)
    for item in opt.items:
        place = ctx.places.get(item.ref_id)
        if place is None:
            violations.append(f"unknown place id {item.ref_id!r}: only use ids returned by the search tools")
            continue
        if grounded and item.ref_id not in ctx.seen_ids:
            violations.append(f"{place.name} ({item.ref_id}) was not returned by a search in this run")
            continue
        if not is_hhmm(item.start):
            violations.append(f"{place.name}: start {item.start!r} is not HH:MM")
            continue
        start = to_min(item.start)
        typical = place.typical_min
        if place.kind == "event":
            duration = place.duration_min or typical
        else:
            duration = item.duration_min or typical
            if duration < 30 or duration > max(2 * typical, typical + 60):
                violations.append(f"{place.name}: {duration} min is unrealistic (typical {typical} min)")
        resolved.append((item, place, start, duration))
    resolved.sort(key=lambda r: r[2])

    items_out: list[PlanItemOut] = []
    prev_place, prev_end = ctx.start_point, None
    legs: list[Leg] = []
    adjusted: list[str] = []
    spend = 0
    for item, place, wanted, duration in resolved:
        # Code owns the clock: travel into this stop, then the earliest workable start at or after the model's
        # choice (next reachable showtime, or within opening hours). Only an impossible stop is a violation.
        depart = prev_end if prev_end is not None else max(ctx.window_start, wanted - 30)
        lg = travel.leg(ctx.city, prev_place, place, depart, opt.kind)
        legs.append(lg)
        arrive = (prev_end if prev_end is not None else ctx.window_start) + lg.minutes
        start = settle_start(place, wanted, arrive, duration)
        if start is None:
            if place.kind == "event":
                violations.append(f"{place.name}: no showtime ({', '.join(place.start_times)}) you can reach by {fmt(arrive)}")
            else:
                hours = ", ".join(f"{o}–{c}" for o, c in place.open_hours)
                violations.append(f"{place.name} is open {hours}; {duration} min doesn't fit after arriving at {fmt(arrive)}")
            start = max(wanted, arrive)
        elif start != wanted:
            adjusted.append(f"{place.name} {fmt(wanted)}→{fmt(start)}")
        end = start + duration
        # price
        cost = place.base_price
        if item.tier and place.kind != "restaurant":
            tier = next((t for t in place.price_tiers if t.tier.lower() == item.tier.lower()), None)
            if tier is None:
                violations.append(f"{place.name} has no tier {item.tier!r} (tiers: {', '.join(t.tier for t in place.price_tiers)})")
            else:
                cost = tier.price
        spend += cost
        # constraints
        crowd = getattr(place.crowd, slot_of(start))
        if reason := rule_violation(place, rules):
            violations.append(f"{place.name} is {reason}")
        if rules.avoid_crowds and crowd == "high":
            violations.append(f"{place.name} is crowded ({slot_of(start)}) and you asked to avoid crowds")
        if not place.indoor and "weather_down" not in ctx.simulate:
            bad = [h for m in range(start, end, 30) if (h := hour_weather(ctx.city, m)) and is_bad(h)]
            if bad:
                msg = f"{place.name} is outdoors at {fmt(start)} with {bad_reason(bad[0])}"
                if any(_WEATHER_WORDS.search(t) for t in opt.tradeoffs):
                    warnings.append(msg)
                else:
                    violations.append(msg + ": move it indoors or explain the weather in tradeoffs")
        if place.id in ctx.past_place_ids:
            warnings.append(f"{place.name} was in one of your past plans")
        if len(item.why_it_fits.strip()) < 10:
            violations.append(f"{place.name}: explain why_it_fits this user")
        items_out.append(PlanItemOut(
            ref_id=place.id, name=place.name, kind=place.kind, label=place.label, area=place.area,
            start=fmt(start), end=fmt(end), duration_min=duration, cost_inr=cost,
            tier=item.tier if place.kind != "restaurant" else None, indoor=place.indoor, crowd=crowd,
            veg=place.veg, blurb=place.blurb, why_it_fits=item.why_it_fits.strip(), leg_before=lg,
        ))
        prev_place, prev_end = place, end

    leg_home = None
    first_leave = ctx.window_start
    home_by = ctx.window_start
    if resolved:
        first_leave = to_min(items_out[0].start) - legs[0].minutes
        leg_home = travel.leg(ctx.city, prev_place, ctx.start_point, prev_end, opt.kind)
        legs.append(leg_home)
        home_by = prev_end + leg_home.minutes
        if home_by > ctx.window_end + WINDOW_GRACE_MIN:
            violations.append(
                f"you'd be back at {fmt(home_by)}, {home_by - ctx.window_end} min past your window ({fmt(ctx.window_end)})"
            )
        elif home_by > ctx.window_end:
            warnings.append(f"back at {fmt(home_by)}, {home_by - ctx.window_end} min past your window")
        if rules.end_by and is_hhmm(rules.end_by) and home_by > to_min(rules.end_by):
            violations.append(f"you'd be back at {fmt(home_by)}, after your {rules.end_by} limit")

    travel_inr = sum(lg.fare_inr for lg in legs)
    total = spend + travel_inr
    budget = prefs.budget_inr
    if total > budget:
        over = total - budget
        if opt.kind == "recommended" and total <= budget * OVER_BUDGET_OK and any(_BUDGET_WORDS.search(t) for t in opt.tradeoffs):
            warnings.append(f"{rupees(over)} over budget (allowed: explained in tradeoffs)")
        elif opt.kind == "recommended" and total <= budget * OVER_BUDGET_OK:
            violations.append(f"{rupees(total)} is {rupees(over)} over the {rupees(budget)} budget: explain it in tradeoffs or cut cost")
        else:
            violations.append(f"{rupees(total)} all-in is {rupees(over)} over the {rupees(budget)} budget")

    matched = interest_categories(prefs.interests)
    food_tags = interest_restaurant_tags(prefs.interests)
    wants_food = any(w in " ".join(prefs.interests).lower() for w in ("food", "eat", "cafe", "café", "coffee"))
    if resolved and (matched or food_tags) and not any(
        (p.kind != "restaurant" and p.category in matched) or (p.kind == "restaurant" and (wants_food or set(p.tags) & food_tags))
        for _, p, _, _ in resolved
    ):
        warnings.append("no stop matches the user's interests directly")
    available = ctx.window_end - ctx.window_start
    at_stops = sum(d for _, _, _, d in resolved)
    if resolved and available >= 120 and at_stops < MIN_FILL * available:
        msg = f"only {at_stops} min at stops in a {available // 60}h window"
        if any(_SHORT_WORDS.search(t) for t in opt.tradeoffs):
            warnings.append(msg)
        else:
            violations.append(msg + ": add a stop or stay longer, or explain in tradeoffs why a short plan is best")
    stops = sum(1 for _, p, _, _ in resolved if p.kind != "restaurant")
    if prefs.energy == "low" and stops >= 3 and prefs.available_hours <= 5:
        warnings.append("that's a lot of stops for a tired day")

    status = "fail" if violations else ("warn" if warnings else "pass")
    return PlanOptionOut(
        kind=opt.kind, title=opt.title.strip() or KIND_LABELS[opt.kind], pitch=opt.pitch.strip(), items=items_out,
        leg_home=leg_home, tradeoffs=[t.strip() for t in opt.tradeoffs if t.strip()],
        totals=Totals(
            cost_inr=total, spend_inr=spend, travel_inr=travel_inr,
            activity_min=sum(i.duration_min for i in items_out),
            travel_min=sum(lg.minutes for lg in legs),
            start=fmt(first_leave), end=fmt(home_by), budget_inr=budget,
            available_min=ctx.window_end - ctx.window_start,
        ),
        validation=Validation(status=status, violations=violations, warnings=warnings, adjusted=adjusted),
        source=source,
    )


def settle_start(place, wanted: int, arrive: int, duration: int) -> int | None:
    """Earliest start at or after `wanted` that the user can actually make after arriving at `arrive`."""
    if place.kind == "event":
        ok = [to_min(t) for t in place.start_times if to_min(t) >= max(wanted, arrive - TRAVEL_SLACK_MIN)]
        return min(ok) if ok else None
    earliest = max(wanted, -(-arrive // 5) * 5)  # arrive, rounded up to 5 minutes
    for o, c in sorted(place.open_hours):
        s = max(earliest, to_min(o))
        if s + duration <= to_min(c):
            return s
    return None


def feedback(out: PlanOptionOut) -> dict:
    """What the model sees back from validation: totals + problems, no need to echo the plan."""
    t = out.totals
    return {
        "kind": out.kind,
        "status": out.validation.status,
        "totals": {
            "cost_inr": t.cost_inr, "budget_inr": t.budget_inr, "tickets_food_inr": t.spend_inr, "travel_inr": t.travel_inr,
            "leave": t.start, "back": t.end, "travel_min": t.travel_min,
        },
        "legs": [f"{i.leg_before.mode} {i.leg_before.minutes}m ₹{i.leg_before.fare_inr} → {i.name}" for i in out.items if i.leg_before]
        + ([f"{out.leg_home.mode} {out.leg_home.minutes}m ₹{out.leg_home.fare_inr} → back"] if out.leg_home else []),
        "violations": out.validation.violations,
        "warnings": out.validation.warnings,
        **({"adjusted_times": out.validation.adjusted} if out.validation.adjusted else {}),
    }


async def _emit_validation(ctx, out: PlanOptionOut) -> None:
    await ctx.emit({
        "type": "validation", "kind": out.kind, "status": out.validation.status,
        "totals": out.totals.model_dump(), "violations": out.validation.violations, "warnings": out.validation.warnings,
    })


# --------------------------------------------------------------------------- validate_plan


class ValidateArgs(BaseModel):
    options: list[PlanOptionIn] = Field(min_length=1, max_length=3, description="1–3 draft options to check")


VALIDATE_DESCRIPTION = (
    "Check draft options against budget (all-in: tickets + food + travel), the time window (including travel "
    "between stops and the ride back), opening hours/showtimes, constraints, crowds and weather. Returns the real "
    "totals and a list of violations to fix. Call it before submit_plans."
)


async def validate_plan(ctx, args: ValidateArgs) -> dict:
    results = []
    for opt in args.options:
        ctx.drafts[opt.kind] = opt  # kept so the loop can rescue validated work if it runs out of turns
        out = evaluate(ctx, opt)
        await _emit_validation(ctx, out)
        results.append(feedback(out))
    return {"results": results}


def summarize_validate(result: dict) -> str:
    return " · ".join(
        f"{KIND_LABELS.get(r['kind'], r['kind'])}: {r['status']} ₹{r['totals']['cost_inr']}"
        + (f" ({len(r['violations'])} issues)" if r["violations"] else "")
        for r in result.get("results", [])
    )


# --------------------------------------------------------------------------- submit_plans (done signal)


class SubmitArgs(BaseModel):
    options: list[PlanOptionIn] = Field(
        min_length=3, max_length=3, description="exactly one each: time_saver, recommended, value_for_money"
    )
    assumptions: list[str] = Field(default_factory=list, description="assumptions you made, in plain words")
    weather_note: str | None = Field(None, description="one line on how the weather shaped the plan")


SUBMIT_DESCRIPTION = (
    "Submit the final three options. This ends the task: it is accepted only if all three pass validation; "
    "otherwise you get the problems back to fix. Call it once your validate_plan results are clean."
)


async def submit_plans(ctx, args: SubmitArgs) -> dict:
    ctx.submit_attempts += 1
    options = args.options
    kinds = [o.kind for o in options]
    if sorted(kinds) != sorted(KIND_ORDER):
        return {"status": "rejected", "problems": {"options": [f"need exactly one each of {list(KIND_ORDER)}, got {kinds}"]}}

    outs = {o.kind: evaluate(ctx, o) for o in options}
    seen_sets: dict[tuple, str] = {}
    for kind in KIND_ORDER:
        key = tuple(sorted(i.ref_id for i in outs[kind].items))
        if key in seen_sets:
            outs[kind].validation.violations.append(f"same stops as {KIND_LABELS[seen_sets[key]]}: make the options differ")
            outs[kind].validation.status = "fail"
        else:
            seen_sets[key] = kind
    _ordering_warnings(outs)
    for kind in KIND_ORDER:
        await _emit_validation(ctx, outs[kind])

    for kind, out in outs.items():
        if out.validation.status != "fail":
            ctx.best[kind] = out
    ctx.submitted_assumptions = args.assumptions
    ctx.submitted_weather_note = args.weather_note

    problems = {k: o.validation.violations for k, o in outs.items() if o.validation.status == "fail"}
    if not problems:
        ctx.accepted = True
        return {"status": "accepted", "message": "All three options passed. You're done: reply with one short closing line."}
    left = ctx.limits.caps.get("submit_plans", 3) - ctx.submit_attempts
    return {
        "status": "rejected",
        "problems": problems,
        "attempts_left": max(0, left),
        "hint": "fix only the failing options and submit all three again" if left > 0 else "no attempts left",
    }


def _ordering_warnings(outs: dict[str, PlanOptionOut]) -> None:
    ts, vfm = outs["time_saver"], outs["value_for_money"]
    if ts.totals.travel_min > min(o.totals.travel_min for o in outs.values()):
        ts.validation.warnings.append("another option has less travel than the Time Saver")
    if vfm.totals.cost_inr > min(o.totals.cost_inr for o in outs.values()):
        vfm.validation.warnings.append("another option is cheaper than Value for Money")
    for o in (ts, vfm):
        if o.validation.status == "pass" and o.validation.warnings:
            o.validation.status = "warn"


def summarize_submit(result: dict) -> str:
    if result.get("status") == "accepted":
        return "accepted: all three options valid"
    probs = result.get("problems", {})
    n = sum(len(v) for v in probs.values())
    return f"rejected: {n} problem(s) in {', '.join(probs)} · attempts left {result.get('attempts_left', 0)}"
