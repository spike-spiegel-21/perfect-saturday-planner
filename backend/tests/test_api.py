"""End-to-end over HTTP with no model at all: rules-based intake + rule-based planner, memory across sessions."""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import DisabledLLM
from app.main import create_app
from app.memory import Store


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"), mock_latency_ms=0, rate_user_per_day=3)
    app = create_app(settings, llm=DisabledLLM(), store=Store(settings.db_path))
    with TestClient(app) as c:
        yield c


def sse(body: str) -> list[dict]:
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


def chat(client, sid, *texts):
    turn = None
    for t in texts:
        r = client.post(f"/api/sessions/{sid}/messages", json={"text": t})
        assert r.status_code == 200, r.text
        turn = r.json()
    return turn


ANSWERS = ["i am at the gurgaon, and my budget is ₹3000", "4 hours", "tired but want to do something fun",
           "food, live music", "vegetarian, avoid crowded places"]


def test_health(client):
    body = client.get("/health").json()
    assert body["ok"] and body["llm_configured"] is False


def test_full_journey_and_memory(client):
    s = client.post("/api/sessions", json={"user_id": "user-123"}).json()
    assert s["status"] == "collecting" and s["turn"]["reply"].startswith("Hey!") and s["turn"]["pills"] == []
    sid = s["session_id"]

    turn = chat(client, sid, *ANSWERS)
    assert turn["ready"] and turn["slots"]["rules"]["vegetarian"]

    r = client.post(f"/api/sessions/{sid}/plan")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = sse(r.text)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "run_started" and kinds[-1] == "done" and "plans" in kinds and "fallback" in kinds
    run = next(e for e in events if e["type"] == "plans")["run"]
    assert [o["kind"] for o in run["options"]] == ["time_saver", "recommended", "value_for_money"]
    assert run["fallback"] and "unavailable" in run["fallback_reason"]
    for o in run["options"]:
        assert o["totals"]["cost_inr"] <= 3000 * 1.1
        assert all(i["veg"] != "non_veg" for i in o["items"] if i["kind"] == "restaurant")

    s = client.get(f"/api/sessions/{sid}").json()
    assert s["status"] == "planned" and s["last_run"]["run_id"] == run["run_id"] and s["last_trace"]
    assert s["messages"][-1]["run_id"] == run["run_id"]

    assert client.post(f"/api/sessions/{sid}/choose", json={"run_id": run["run_id"], "kind": "value_for_money"}).json()["ok"]
    mem = client.get("/api/users/user-123/memory").json()
    assert any("Gurgaon" in line for line in mem["summary"]) and mem["profile"]["last_pick"] == "value_for_money"

    s2 = client.post("/api/sessions", json={"user_id": "user-123"}).json()
    assert s2["turn"]["reply"].startswith("Welcome back") and "Gurgaon" in s2["memory_hint"]
    turn = chat(client, s2["session_id"], "hi")
    assert turn["pills"][0]["remembered"] and turn["pills"][0]["value"] == "Gurgaon"

    assert client.delete("/api/users/user-123").json()["ok"]
    assert client.get("/api/users/user-123/memory").json()["profile"] is None


def test_refine_after_plan(client):
    sid = client.post("/api/sessions", json={"user_id": "user-456"}).json()["session_id"]
    chat(client, sid, *ANSWERS)
    client.post(f"/api/sessions/{sid}/plan")
    turn = chat(client, sid, "actually my budget is ₹1500")
    assert turn["ready"] and turn["slots"]["budget_inr"] == 1500
    events = sse(client.post(f"/api/sessions/{sid}/plan").text)
    run = next(e for e in events if e["type"] == "plans")["run"]
    assert all(o["totals"]["budget_inr"] == 1500 for o in run["options"])


def test_plan_refuses_until_intake_is_complete(client):
    sid = client.post("/api/sessions", json={"user_id": "user-789"}).json()["session_id"]
    chat(client, sid, "delhi, ₹1000")
    r = client.post(f"/api/sessions/{sid}/plan")
    assert r.status_code == 400 and "available_time" in r.json()["detail"]


def test_simulated_failures_and_rate_limit(client):
    sid = client.post("/api/sessions", json={"user_id": "user-999"}).json()["session_id"]
    chat(client, sid, "mumbai ₹2000", "5 hours", "social", "comedy, food", "none")
    events = sse(client.post(f"/api/sessions/{sid}/plan?simulate=weather_down,no_restaurants").text)
    run = next(e for e in events if e["type"] == "plans")["run"]
    assert "unavailable" in run["weather_note"]
    assert all(i["kind"] != "restaurant" for o in run["options"] for i in o["items"])
    client.post(f"/api/sessions/{sid}/plan")
    client.post(f"/api/sessions/{sid}/plan")
    r = client.post(f"/api/sessions/{sid}/plan")
    assert r.status_code == 429


def test_unknown_session_and_bad_input(client):
    assert client.get("/api/sessions/nope").status_code == 404
    sid = client.post("/api/sessions", json={"user_id": "user-000"}).json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/messages", json={"text": ""}).status_code == 422
    assert client.post(f"/api/sessions/{sid}/messages", json={"text": "x" * 1001}).status_code == 422
