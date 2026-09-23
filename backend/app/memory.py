"""Memory: SQLite store for sessions, messages, runs (with traces) and cross-session user profiles.

Short-term memory is the session (slots + conversation, resumable after a reload). Long-term memory is the
profile keyed by an anonymous browser id: home city, budgets, standing constraints, and the places from
past plans so the agent doesn't serve the same Saturday twice.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from app.models import KIND_LABELS, MessageOut, Preferences, RunOut, Slots

SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (user_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, status TEXT NOT NULL, slots TEXT NOT NULL, state TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    meta TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, user_id TEXT NOT NULL, prefs TEXT NOT NULL, run TEXT NOT NULL,
    trace TEXT NOT NULL, chosen TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_session ON runs(session_id, created_at);
CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, count INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS source_cache (key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at REAL NOT NULL);
"""

MAX_PAST_PLACES = 30


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # ------------------------------------------------------------------ sessions

    def create_session(self, user_id: str) -> str:
        sid = uuid.uuid4().hex[:16]
        now = _now()
        self._q(
            "INSERT INTO sessions VALUES (?, ?, 'collecting', ?, ?, ?, ?)",
            (sid, user_id, Slots().model_dump_json(), json.dumps({"asked": {}}), now, now),
        )
        return sid

    def get_session(self, sid: str) -> dict | None:
        rows = self._q("SELECT * FROM sessions WHERE id = ?", (sid,))
        if not rows:
            return None
        r = rows[0]
        return {
            "id": r["id"], "user_id": r["user_id"], "status": r["status"],
            "slots": Slots.model_validate_json(r["slots"]), "state": json.loads(r["state"]),
            "updated_at": r["updated_at"],
        }

    def save_session(self, sid: str, *, status: str | None = None, slots: Slots | None = None, state: dict | None = None) -> None:
        sets, args = ["updated_at = ?"], [_now()]
        if status is not None:
            sets.append("status = ?")
            args.append(status)
        if slots is not None:
            sets.append("slots = ?")
            args.append(slots.model_dump_json())
        if state is not None:
            sets.append("state = ?")
            args.append(json.dumps(state))
        self._q(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", (*args, sid))

    def claim_planning(self, sid: str, stale_before: str) -> bool:
        """Atomically move a session into 'planning' (one run at a time; stale runs can be re-claimed)."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE sessions SET status = 'planning', updated_at = ? "
                "WHERE id = ? AND (status IN ('ready', 'planned') OR (status = 'planning' AND updated_at < ?))",
                (_now(), sid, stale_before),
            )
            return cur.rowcount == 1

    def reset_planning(self) -> None:
        """Runs don't survive a restart; let those sessions plan again."""
        self._q("UPDATE sessions SET status = 'ready' WHERE status = 'planning'")

    # ------------------------------------------------------------------ messages

    def add_message(self, sid: str, role: str, content: str, meta: dict | None = None) -> None:
        self._q(
            "INSERT INTO messages (session_id, role, content, meta, created_at) VALUES (?, ?, ?, ?, ?)",
            (sid, role, content, json.dumps(meta) if meta else None, _now()),
        )

    def messages(self, sid: str, limit: int = 200) -> list[MessageOut]:
        rows = self._q("SELECT role, content, meta FROM messages WHERE session_id = ? ORDER BY id LIMIT ?", (sid, limit))
        out = []
        for r in rows:
            meta = json.loads(r["meta"]) if r["meta"] else {}
            out.append(MessageOut(role=r["role"], content=r["content"], turn=meta.get("turn"), run_id=meta.get("run_id")))
        return out

    # ------------------------------------------------------------------ runs

    def save_run(self, sid: str, user_id: str, prefs: Preferences, run: RunOut, trace: list[dict]) -> None:
        self._q(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, NULL, ?)",
            (run.run_id, sid, user_id, prefs.model_dump_json(), run.model_dump_json(), json.dumps(trace), _now()),
        )

    def last_run(self, sid: str) -> tuple[RunOut, list[dict]] | None:
        rows = self._q("SELECT run, trace, chosen FROM runs WHERE session_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 1", (sid,))
        if not rows:
            return None
        run = RunOut.model_validate_json(rows[0]["run"])
        run.chosen = rows[0]["chosen"]
        return run, json.loads(rows[0]["trace"])

    def get_run(self, run_id: str) -> dict | None:
        rows = self._q("SELECT * FROM runs WHERE id = ?", (run_id,))
        if not rows:
            return None
        r = rows[0]
        return {"session_id": r["session_id"], "user_id": r["user_id"], "run": RunOut.model_validate_json(r["run"])}

    def set_chosen(self, run_id: str, kind: str) -> None:
        self._q("UPDATE runs SET chosen = ? WHERE id = ?", (kind, run_id))

    # ------------------------------------------------------------------ profiles (cross-session memory)

    def profile(self, user_id: str) -> dict | None:
        rows = self._q("SELECT data FROM profiles WHERE user_id = ?", (user_id,))
        return json.loads(rows[0]["data"]) if rows else None

    def _save_profile(self, user_id: str, data: dict) -> None:
        self._q(
            "INSERT INTO profiles VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
            (user_id, json.dumps(data), _now()),
        )

    def remember_run(self, user_id: str, prefs: Preferences, run: RunOut) -> None:
        """Deterministic profile update after a run: no LLM involved in what gets remembered."""
        p = self.profile(user_id) or {"runs": 0, "interest_counts": {}, "past_places": [], "picked_kinds": {}}
        p["runs"] = p.get("runs", 0) + 1
        p["home_city"] = prefs.city
        p["home_city_name"] = prefs.city_name
        p["last_budget"] = prefs.budget_inr
        p["last_hours"] = prefs.available_hours
        p["last_mood"] = prefs.mood
        p["constraints"] = prefs.constraints
        p["rules"] = prefs.rules.model_dump(exclude_defaults=True)
        counts = p.setdefault("interest_counts", {})
        for interest in prefs.interests:
            counts[interest.lower()] = counts.get(interest.lower(), 0) + 1
        rec = next((o for o in run.options if o.kind == "recommended"), None)
        if rec:
            day = date.today().isoformat()
            known = {pp["id"] for pp in p["past_places"]}
            for item in rec.items:
                if item.ref_id not in known:
                    p["past_places"].append({"id": item.ref_id, "name": item.name, "date": day, "picked": False})
        p["past_places"] = p["past_places"][-MAX_PAST_PLACES:]
        p["last_seen"] = _now()
        self._save_profile(user_id, p)

    def remember_choice(self, user_id: str, run: RunOut, kind: str) -> None:
        p = self.profile(user_id)
        if p is None:
            return
        picked = p.setdefault("picked_kinds", {})
        picked[kind] = picked.get(kind, 0) + 1
        p["last_pick"] = kind
        opt = next((o for o in run.options if o.kind == kind), None)
        if opt:
            ids = {i.ref_id: i.name for i in opt.items}
            day = date.today().isoformat()
            for pp in p["past_places"]:
                if pp["id"] in ids:
                    pp["picked"] = True
            known = {pp["id"] for pp in p["past_places"]}
            p["past_places"] += [{"id": i, "name": n, "date": day, "picked": True} for i, n in ids.items() if i not in known]
            p["past_places"] = p["past_places"][-MAX_PAST_PLACES:]
        self._save_profile(user_id, p)

    def forget(self, user_id: str) -> None:
        self._q("DELETE FROM profiles WHERE user_id = ?", (user_id,))

    # ------------------------------------------------------------------ live-data cache

    def cache_get(self, key: str):
        rows = self._q("SELECT value, expires_at FROM source_cache WHERE key = ?", (key,))
        if not rows or rows[0]["expires_at"] < time.time():
            return None
        return json.loads(rows[0]["value"])

    def cache_set(self, key: str, value, ttl_s: float) -> None:
        self._q(
            "INSERT INTO source_cache VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
            (key, json.dumps(value), time.time() + ttl_s),
        )

    # ------------------------------------------------------------------ rate limits

    def bump(self, key: str) -> int:
        with self._lock:
            self._db.execute(
                "INSERT INTO counters VALUES (?, 1) ON CONFLICT(key) DO UPDATE SET count = count + 1", (key,)
            )
            return self._db.execute("SELECT count FROM counters WHERE key = ?", (key,)).fetchone()[0]

    def count(self, key: str) -> int:
        rows = self._q("SELECT count FROM counters WHERE key = ?", (key,))
        return rows[0]["count"] if rows else 0


def memory_summary(profile: dict | None) -> list[str]:
    """At most five plain lines the planner sees about this user."""
    if not profile:
        return []
    lines = [f"Returning user with {profile.get('runs', 0)} past plan(s)."]
    if profile.get("home_city_name"):
        lines.append(f"Planned in {profile['home_city_name']} last time with a ₹{profile.get('last_budget', 0):,} budget.")
    if profile.get("last_pick"):
        lines.append(f"Last time they picked the {KIND_LABELS.get(profile['last_pick'], profile['last_pick'])} option.")
    places = [pp for pp in profile.get("past_places", [])][-8:]
    if places:
        names = ", ".join(pp["name"] + (" (picked)" if pp.get("picked") else "") for pp in places)
        lines.append(f"Places from past plans (avoid repeating unless nothing else fits): {names}.")
    top = sorted(profile.get("interest_counts", {}).items(), key=lambda kv: -kv[1])[:3]
    if top:
        lines.append(f"Recurring interests: {', '.join(k for k, _ in top)}.")
    return lines[:5]


def past_place_ids(profile: dict | None) -> frozenset[str]:
    return frozenset(pp["id"] for pp in (profile or {}).get("past_places", []))
