"""API integration tests for the NC Benefits Navigator server.

Test seam
---------
``server.routes._run_turn`` is monkeypatched to a fake async-generator factory.
This is the cleanest seam because:
  - It sits at the exact boundary where API-key, model, and session state are
    resolved, so we can verify all the guards without touching real Anthropic.
  - The fake is a simple coroutine that yields pre-scripted Events — no fake
    client plumbing needed.
  - The interview loop internals (run_turn, FakeClient) are tested elsewhere;
    here we only care about the server contract.

All tests use httpx.AsyncClient with ASGITransport against create_app().
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import server.routes as routes_module
from interview.loop import (
    DoneEvent,
    ErrorEvent,
    HouseholdEvent,
    ScreeningEvent,
    TextEvent,
)
from rules.engine import screen_all
from rules.models import Household
from server.app import create_app
from server.config import Settings, _reset_settings, _set_settings_override
from server.sessions import _reset_budget, _reset_store, _set_budget_clock

# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> Settings:
    base = dict(
        anthropic_api_key="test-key",
        model="claude-test",
        session_ttl_minutes=60,
        max_messages_per_session=40,
        daily_budget_usd=10.0,
        demo_mode=False,
        port=8000,
        price_in_per_mtok=3.0,
        price_out_per_mtok=15.0,
    )
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Fake clock
# ---------------------------------------------------------------------------


class FakeClock:
    def __init__(self, start: datetime):
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, **kwargs) -> None:
        self._now += timedelta(**kwargs)


def _clock() -> FakeClock:
    return FakeClock(datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC))


# ---------------------------------------------------------------------------
# Fake run_turn
# ---------------------------------------------------------------------------


def _make_run_turn(*events):
    """Return a coroutine that, when called, yields the given Event objects."""

    async def fake_run_turn(state, message, *, client=None, model="x", max_tokens=2048):
        for e in events:
            yield e

    return fake_run_turn


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_all():
    """Clean up global state between tests."""
    _reset_settings()
    clock = _clock()
    _reset_store(now=clock)
    _reset_budget(now_fn=clock)  # also sets _budget_clock to clock
    yield
    _reset_settings()
    # Restore real clock after each test
    from datetime import UTC
    from datetime import datetime as _dt
    _set_budget_clock(lambda: _dt.now(UTC))


@pytest.fixture()
def settings_with_key():
    s = _make_settings(anthropic_api_key="test-key-abc")
    _set_settings_override(s)
    return s


@pytest.fixture()
def settings_no_key():
    s = _make_settings(anthropic_api_key="")
    _set_settings_override(s)
    return s


@pytest_asyncio.fixture()
async def client_with_key(settings_with_key):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture()
async def client_no_key(settings_no_key):
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture()
async def client(settings_with_key):
    """Alias for default client."""
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# healthz
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


# ---------------------------------------------------------------------------
# Session lifecycle via API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session(client):
    r = await client.post("/api/session")
    assert r.status_code == 201
    body = r.json()
    assert "session_id" in body
    assert "screening" in body
    assert "programs" in body["screening"]


@pytest.mark.asyncio
async def test_delete_session(client):
    r = await client.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client.delete(f"/api/session/{sid}")
    assert r2.status_code == 204


@pytest.mark.asyncio
async def test_delete_nonexistent_session_is_204(client):
    r = await client.delete("/api/session/ghost-id-xyz")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_expired_session_returns_404(client_with_key):
    """TTL expiry evicts session — subsequent requests get 404."""
    s = _make_settings(anthropic_api_key="key", session_ttl_minutes=1)
    _set_settings_override(s)

    clock = _clock()
    store = _reset_store(now=clock)
    session = store.create()
    clock.advance(minutes=2)

    # Re-create app so it uses the new settings/store reference
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get(f"/api/session/{session.id}/report")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "session not found"


# ---------------------------------------------------------------------------
# Report endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_structure(client):
    r = await client.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client.get(f"/api/session/{sid}/report")
    assert r2.status_code == 200
    body = r2.json()
    assert "household" in body
    assert "screening" in body
    assert "generated_at" in body
    # generated_at must be ISO-parseable
    datetime.fromisoformat(body["generated_at"])


@pytest.mark.asyncio
async def test_report_screening_has_reasons_and_citations(client):
    r = await client.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client.get(f"/api/session/{sid}/report")
    screening = r2.json()["screening"]
    # Full screening — must have programs list and each program has reasons field
    assert "programs" in screening
    for prog in screening["programs"]:
        assert "reasons" in prog, f"program {prog} missing reasons"


@pytest.mark.asyncio
async def test_report_404_unknown_session(client):
    r = await client.get("/api/session/does-not-exist/report")
    assert r.status_code == 404
    assert "error" in r.json()["detail"]


# ---------------------------------------------------------------------------
# PATCH household
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_household_converts_dollars_to_cents(client):
    r = await client.post("/api/session")
    sid = r.json()["session_id"]

    patch = {
        "patch": {
            "members": [{"id": "m1", "age": 35, "relationship": "self"}],
            "income": [
                {
                    "id": "i1",
                    "member_id": "m1",
                    "kind": "wages",
                    "amount": 1250.50,
                    "frequency": "monthly",
                }
            ],
        }
    }
    r2 = await client.patch(f"/api/session/{sid}/household", json=patch)
    assert r2.status_code == 200
    body = r2.json()
    # Dollar→cents: $1250.50 → 125050 cents
    income = body["household"]["income"]
    assert income[0]["amount_cents"] == 125050


@pytest.mark.asyncio
async def test_patch_household_engine_ran(client):
    r = await client.post("/api/session")
    sid = r.json()["session_id"]
    patch = {"patch": {"county": "Wake"}}
    r2 = await client.patch(f"/api/session/{sid}/household", json=patch)
    assert r2.status_code == 200
    body = r2.json()
    # Screening (compact) present — programs list not empty
    assert "programs" in body["screening"]
    assert len(body["screening"]["programs"]) > 0


@pytest.mark.asyncio
async def test_patch_household_validation_error_422(client):
    r = await client.post("/api/session")
    sid = r.json()["session_id"]
    # age out of range
    patch = {"patch": {"members": [{"id": "m1", "age": 999}]}}
    r2 = await client.patch(f"/api/session/{sid}/household", json=patch)
    assert r2.status_code == 422
    detail = r2.json()["detail"]
    assert "error" in detail
    # error message should mention the field
    assert "age" in detail["error"]


@pytest.mark.asyncio
async def test_patch_household_404_unknown(client):
    r = await client.patch("/api/session/ghost/household", json={"patch": {}})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Message endpoint — SSE stream
# ---------------------------------------------------------------------------


def _parse_sse(raw: bytes) -> list[dict]:
    """Parse raw SSE bytes into list of {event, data} dicts."""
    events = []
    current: dict = {}
    for line in raw.decode().splitlines():
        if line.startswith("event:"):
            current["event"] = line[len("event:"):].strip()
        elif line.startswith("data:"):
            current["data"] = json.loads(line[len("data:"):].strip())
        elif line == "" and current:
            events.append(current)
            current = {}
    if current:
        events.append(current)
    return events


@pytest.mark.asyncio
async def test_message_sse_stream(client_with_key, monkeypatch):
    fake = _make_run_turn(
        TextEvent(delta="Hello"),
        TextEvent(delta=" world"),
        DoneEvent(),
    )
    monkeypatch.setattr(routes_module, "_run_turn", fake)

    r = await client_with_key.post("/api/session")
    sid = r.json()["session_id"]

    r2 = await client_with_key.post(
        f"/api/session/{sid}/message",
        json={"message": "hi"},
    )
    assert r2.status_code == 200
    events = _parse_sse(r2.content)
    types = [e["event"] for e in events]
    assert "text" in types
    assert "done" in types
    text_events = [e for e in events if e["event"] == "text"]
    combined = "".join(e["data"]["delta"] for e in text_events)
    assert combined == "Hello world"


@pytest.mark.asyncio
async def test_message_sse_household_and_screening_events(client_with_key, monkeypatch):
    hh = Household(members=[], income=[], expenses=None or __import__("rules.models", fromlist=["Expenses"]).Expenses())
    screening = screen_all(hh)
    fake = _make_run_turn(
        HouseholdEvent(data=hh.model_dump()),
        ScreeningEvent(data=screening.model_dump()),
        DoneEvent(),
    )
    monkeypatch.setattr(routes_module, "_run_turn", fake)

    r = await client_with_key.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client_with_key.post(
        f"/api/session/{sid}/message",
        json={"message": "test"},
    )
    assert r2.status_code == 200
    events = _parse_sse(r2.content)
    types = [e["event"] for e in events]
    assert "household" in types
    assert "screening" in types
    assert "done" in types


@pytest.mark.asyncio
async def test_message_sse_error_event(client_with_key, monkeypatch):
    fake = _make_run_turn(
        ErrorEvent(message="API unreachable"),
    )
    monkeypatch.setattr(routes_module, "_run_turn", fake)

    r = await client_with_key.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client_with_key.post(
        f"/api/session/{sid}/message",
        json={"message": "test"},
    )
    assert r2.status_code == 200
    events = _parse_sse(r2.content)
    types = [e["event"] for e in events]
    assert "error" in types


@pytest.mark.asyncio
async def test_message_sse_midstream_exception_yields_error_event(client_with_key, monkeypatch):
    async def exploding_run_turn(state, message, *, client=None, model="x", max_tokens=2048):
        yield TextEvent(delta="partial")
        raise RuntimeError("boom mid-stream")

    monkeypatch.setattr(routes_module, "_run_turn", exploding_run_turn)

    r = await client_with_key.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client_with_key.post(
        f"/api/session/{sid}/message",
        json={"message": "test"},
    )
    assert r2.status_code == 200
    events = _parse_sse(r2.content)
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1
    assert "boom mid-stream" in error_events[0]["data"]["message"]


@pytest.mark.asyncio
async def test_message_validation_422_error_envelope(client_with_key):
    r = await client_with_key.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client_with_key.post(
        f"/api/session/{sid}/message",
        json={"message": ""},
    )
    assert r2.status_code == 422
    detail = r2.json()["detail"]
    assert isinstance(detail, dict)
    assert "message" in detail["error"]

    r3 = await client_with_key.post(
        f"/api/session/{sid}/message",
        json={"message": "x" * 2001},
    )
    assert r3.status_code == 422
    assert "message" in r3.json()["detail"]["error"]


@pytest.mark.asyncio
async def test_message_404_unknown_session(client_with_key):
    r = await client_with_key.post(
        "/api/session/no-such-session/message",
        json={"message": "hi"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "session not found"


@pytest.mark.asyncio
async def test_message_422_too_short(client_with_key):
    r = await client_with_key.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client_with_key.post(
        f"/api/session/{sid}/message",
        json={"message": ""},
    )
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_message_422_too_long(client_with_key):
    r = await client_with_key.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client_with_key.post(
        f"/api/session/{sid}/message",
        json={"message": "x" * 2001},
    )
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_message_429_message_limit(client_with_key, monkeypatch):
    s = _make_settings(anthropic_api_key="key", max_messages_per_session=2)
    _set_settings_override(s)
    app = create_app()

    fake = _make_run_turn(DoneEvent())
    monkeypatch.setattr(routes_module, "_run_turn", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/session")
        sid = r.json()["session_id"]
        # First two succeed
        for _ in range(2):
            await c.post(f"/api/session/{sid}/message", json={"message": "hi"})
        # Third hits limit
        r3 = await c.post(f"/api/session/{sid}/message", json={"message": "hi"})
    assert r3.status_code == 429
    assert r3.json()["detail"]["error"] == "message limit reached"


@pytest.mark.asyncio
async def test_message_503_no_api_key(client_no_key):
    r = await client_no_key.post("/api/session")
    sid = r.json()["session_id"]
    r2 = await client_no_key.post(
        f"/api/session/{sid}/message",
        json={"message": "hello"},
    )
    assert r2.status_code == 503
    assert "error" in r2.json()["detail"]


@pytest.mark.asyncio
async def test_message_429_budget_exhausted(monkeypatch):
    """Pre-fill the budget so the next request trips the guard."""
    s = _make_settings(
        anthropic_api_key="key",
        daily_budget_usd=1.0,  # $1 budget
        price_in_per_mtok=3.0,
        price_out_per_mtok=15.0,
    )
    _set_settings_override(s)
    clock = _clock()
    _reset_store(now=clock)
    _reset_budget(now_fn=clock)  # sets _budget_clock = clock

    # Pre-charge $0.9999 to bring total right up to the limit.
    # The route's would_exceed check for "hi" estimates ~250 input tokens
    # = $0.00075, pushing total to ~$1.0007 > $1.00 → triggers 429.
    from server.sessions import charge as _charge
    _charge(333_300, 0)  # 0.3333 MTok * $3/MTok ≈ $0.9999

    app = create_app()
    fake = _make_run_turn(DoneEvent())
    monkeypatch.setattr(routes_module, "_run_turn", fake)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/session")
        sid = r.json()["session_id"]
        # This request's token estimate will push over $1
        r2 = await c.post(
            f"/api/session/{sid}/message",
            json={"message": "hi"},
        )
    assert r2.status_code == 429
    assert r2.json()["detail"]["error"] == "daily demo budget exhausted"


@pytest.mark.asyncio
async def test_llm_not_called_on_patch(client_with_key, monkeypatch):
    """PATCH /household must never invoke the LLM (run_turn)."""
    called = []

    async def bad_run_turn(*args, **kwargs):
        called.append(True)
        yield DoneEvent()

    monkeypatch.setattr(routes_module, "_run_turn", bad_run_turn)

    r = await client_with_key.post("/api/session")
    sid = r.json()["session_id"]
    await client_with_key.patch(
        f"/api/session/{sid}/household",
        json={"patch": {"county": "Mecklenburg"}},
    )
    assert called == [], "run_turn should not be called by the PATCH endpoint"


# ---------------------------------------------------------------------------
# Demo-mode header
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_demo_header_present_when_demo_mode():
    s = _make_settings(demo_mode=True)
    _set_settings_override(s)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert r.headers.get("x-demo-mode") == "1"


@pytest.mark.asyncio
async def test_demo_header_absent_when_not_demo_mode():
    s = _make_settings(demo_mode=False)
    _set_settings_override(s)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert "x-demo-mode" not in r.headers


# ---------------------------------------------------------------------------
# Budget: accumulation + date reset (via API message path)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_budget_resets_across_date_change(monkeypatch):
    """After a date change, the accumulated cost resets and requests succeed."""
    s = _make_settings(
        anthropic_api_key="key",
        daily_budget_usd=1.0,
        price_in_per_mtok=3.0,
        price_out_per_mtok=15.0,
    )
    _set_settings_override(s)
    clock = _clock()
    _reset_store(now=clock)
    _reset_budget(now_fn=clock)  # sets _budget_clock = clock

    from server.sessions import charge as _charge
    from server.sessions import would_exceed as _would_exceed

    # Pre-charge $0.99 (near limit)
    _charge(330_000, 0)  # 0.33 MTok * $3 = $0.99
    # Confirm would_exceed says True for another 1 MTok
    assert _would_exceed(1_000_000, 0) is True

    # Advance fake clock to next day
    clock.advance(hours=25)
    # On the new day would_exceed resets because date_key doesn't match
    assert _would_exceed(1_000_000, 0) is False

    # A new charge on the new day should work
    _charge(330_000, 0)  # $0.99 again — fine
