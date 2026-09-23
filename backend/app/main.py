"""FastAPI app: sessions and conversational intake, the streaming planner, and memory endpoints.

Run with: uv run uvicorn app.main:create_app --factory --reload
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.agent.loop import run_agent
from app.config import Settings, load_settings
from app.data import load_city
from app.intake import TurnState, greeting, handle_turn, missing_fields, to_preferences
from app.llm import LLM, DisabledLLM, OpenRouterLLM
from app.memory import Store, memory_summary, past_place_ids
from app.models import AssistantTurn, ChooseIn, CreateSessionIn, MessageIn, RunOut, SessionOut

log = logging.getLogger("planner")
SIMULATIONS = {"weather_down", "no_restaurants", "llm_down"}
STALE_RUN = timedelta(minutes=4)


def create_app(settings: Settings | None = None, *, llm: LLM | None = None, store: Store | None = None) -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = settings or load_settings()
    store = store or Store(settings.db_path)
    store.reset_planning()
    if llm is None:
        llm = (
            OpenRouterLLM(settings.openrouter_api_key, settings.model, settings.base_url,
                          settings.limits.llm_timeout_s, settings.app_url)
            if settings.openrouter_api_key else DisabledLLM()
        )
    app = FastAPI(title="Perfect Saturday Planner", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.allowed_origins), allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )
    tasks: set[asyncio.Task] = set()

    def session_or_404(sid: str) -> dict:
        sess = store.get_session(sid)
        if sess is None:
            raise HTTPException(404, "Session not found. Start a new plan.")
        if sess["status"] == "planning" and sess["updated_at"] < _iso(datetime.now(timezone.utc) - STALE_RUN):
            store.save_session(sid, status="ready")
            sess["status"] = "ready"
        return sess

    def session_out(sid: str, memory_hint: str | None = None) -> SessionOut:
        sess = session_or_404(sid)
        msgs = store.messages(sid)
        turn = next((m.turn for m in reversed(msgs) if m.role == "assistant" and m.turn), None)
        last = store.last_run(sid)
        if memory_hint is None:
            memory_hint = greeting(store.profile(sess["user_id"]))[1]
        return SessionOut(
            session_id=sid, user_id=sess["user_id"], status=sess["status"], slots=sess["slots"], messages=msgs,
            turn=turn, last_run=last[0] if last else None, last_trace=last[1] if last else [], memory_hint=memory_hint,
        )

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "model": settings.model, "llm_configured": not isinstance(llm, DisabledLLM)}

    @app.post("/api/sessions", response_model=SessionOut)
    def create_session(body: CreateSessionIn) -> SessionOut:
        sid = store.create_session(body.user_id)
        turn, hint = greeting(store.profile(body.user_id))
        store.add_message(sid, "assistant", turn.reply, {"turn": turn.model_dump()})
        return session_out(sid, memory_hint=hint)

    @app.get("/api/sessions/{sid}", response_model=SessionOut)
    def get_session(sid: str) -> SessionOut:
        return session_out(sid)

    @app.post("/api/sessions/{sid}/messages", response_model=AssistantTurn)
    async def post_message(sid: str, body: MessageIn) -> AssistantTurn:
        sess = session_or_404(sid)
        if sess["status"] == "planning":
            raise HTTPException(409, "Still planning your Saturday. Give me a few seconds.")
        state = TurnState.load(sess["state"])
        store.add_message(sid, "user", body.text.strip())
        res = await handle_turn(
            llm, body.text.strip(), sess["slots"], state, status=sess["status"], profile=store.profile(sess["user_id"])
        )
        if res.turn.ready:
            status = "ready"
        else:
            status = "planned" if sess["status"] in {"planned", "ready"} and not missing_fields(res.slots) else "collecting"
        store.save_session(sid, status=status, slots=res.slots, state=res.state.dump())
        store.add_message(sid, "assistant", res.turn.reply, {"turn": res.turn.model_dump()})
        return res.turn

    @app.post("/api/sessions/{sid}/plan")
    async def plan(sid: str, request: Request, simulate: str | None = None) -> StreamingResponse:
        sess = session_or_404(sid)
        slots = sess["slots"]
        if missing_fields(slots):
            raise HTTPException(400, f"Still need: {', '.join(missing_fields(slots))}.")
        sim = frozenset(s for s in (simulate or "").split(",") if s in SIMULATIONS) if settings.allow_simulation else frozenset()
        user_id = sess["user_id"]
        ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
        day = date.today().isoformat()
        keys = [(f"plan:user:{user_id}:{day}", settings.rate_user_per_day),
                (f"plan:ip:{ip}:{day}", settings.rate_ip_per_day),
                (f"plan:all:{day}", settings.rate_global_per_day)]
        if any(store.count(k) >= limit for k, limit in keys):
            raise HTTPException(429, "That's today's planning limit for this demo. Come back tomorrow!")
        if not store.claim_planning(sid, _iso(datetime.now(timezone.utc) - STALE_RUN)):
            raise HTTPException(409, "A plan is already being made for this session.")
        for k, _ in keys:
            store.bump(k)

        state = TurnState.load(sess["state"])
        prefs = to_preferences(slots)
        profile = store.profile(user_id)
        previous = None
        if state.refinement and (last := store.last_run(sid)):
            previous = [
                {"kind": o.kind, "stops": [i.name for i in o.items], "cost": o.totals.cost_inr} for o in last[0].options
            ]
        run_id = uuid.uuid4().hex[:12]
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: dict) -> None:
            await queue.put(event)

        async def worker() -> None:
            try:
                result = await run_agent(
                    prefs, load_city(prefs.city), llm, emit, run_id=run_id, limits=settings.limits,
                    effort=settings.planner_effort, memory_summary=memory_summary(profile),
                    past_place_ids=past_place_ids(profile), refinement=state.refinement, previous=previous,
                    simulate=sim, mock_latency_s=settings.mock_latency_ms / 1000, extra_assumptions=state.assumed,
                )
                store.save_run(sid, user_id, prefs, result.run, result.trace)
                store.remember_run(user_id, prefs, result.run)
                store.add_message(sid, "assistant", _run_message(result.run, prefs.city_name), {"run_id": run_id})
                state.refinement = None
                store.save_session(sid, status="planned", state=state.dump())
            except Exception:
                log.exception("planning run %s failed", run_id)
                store.save_session(sid, status="ready")
                await queue.put({"type": "error", "message": "Something went wrong while planning. Please try again."})
            finally:
                await queue.put({"type": "done"})
                await queue.put(None)

        task = asyncio.create_task(worker())  # keeps running (and saves) even if the client disconnects
        tasks.add(task)
        task.add_done_callback(tasks.discard)

        async def stream():
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=10)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue
                if event is None:
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            stream(), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
        )

    @app.post("/api/sessions/{sid}/choose")
    def choose(sid: str, body: ChooseIn) -> dict:
        sess = session_or_404(sid)
        row = store.get_run(body.run_id)
        if row is None or row["session_id"] != sid:
            raise HTTPException(404, "Plan not found.")
        run: RunOut = row["run"]
        if body.kind not in {o.kind for o in run.options}:
            raise HTTPException(400, "That option isn't in this plan.")
        store.set_chosen(body.run_id, body.kind)
        store.remember_choice(sess["user_id"], run, body.kind)
        return {"ok": True}

    @app.get("/api/users/{uid}/memory")
    def get_memory(uid: str) -> dict:
        profile = store.profile(uid)
        return {"summary": memory_summary(profile), "profile": profile}

    @app.delete("/api/users/{uid}")
    def forget(uid: str) -> dict:
        store.forget(uid)
        return {"ok": True}

    app.state.settings, app.state.store, app.state.llm = settings, store, llm
    return app


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _run_message(run: RunOut, city_name: str) -> str:
    if not run.options:
        return "I couldn't fit anything into that window. Try a longer window or a different time."
    text = f"Here are {len(run.options)} ways to spend your Saturday in {city_name}."
    if run.fallback:
        text += f" (Rule-based backup: {run.fallback_reason}.)"
    return text

