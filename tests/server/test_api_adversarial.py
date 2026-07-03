"""Adversarial API tests — hostile, malformed, and racing requests.

Every case must produce a clean 4xx or a coherent 200: no 500s, no crashed
session, and a failed patch must never half-apply. Offline (httpx against the
ASGI app); reuses the settings/clock/store fixtures from test_api.py.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import server.routes as routes_module
from interview.loop import DoneEvent, HouseholdEvent, TextEvent
from server.app import create_app
from server.config import _set_settings_override
from server.sessions import _reset_budget, _reset_store
from tests.server.test_api import (  # noqa: F401 — reset_all is autouse
    _clock,
    _make_settings,
    reset_all,
)


@pytest_asyncio.fixture()
async def client():
    _set_settings_override(_make_settings(anthropic_api_key="test-key"))
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _new_session(client: AsyncClient) -> str:
    r = await client.post("/api/session")
    assert r.status_code == 201
    return r.json()["session_id"]


async def _household(client: AsyncClient, sid: str) -> dict:
    r = await client.get(f"/api/session/{sid}/report")
    assert r.status_code == 200
    return r.json()["household"]


# ---------------------------------------------------------------------------
# Malformed patch bodies
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},  # missing 'patch' key
        {"patch": "not an object"},
        {"patch": 42},
        {"patch": None},
        {"patch": ["a", "list"]},
    ],
)
async def test_malformed_patch_body_is_422(client, body):
    sid = await _new_session(client)
    r = await client.patch(f"/api/session/{sid}/household", json=body)
    assert r.status_code == 422
    assert "error" in r.json()["detail"]


@pytest.mark.asyncio
async def test_non_json_patch_body_is_4xx(client):
    sid = await _new_session(client)
    r = await client.patch(
        f"/api/session/{sid}/household",
        content=b"\x00\xffnot json",
        headers={"content-type": "application/json"},
    )
    assert 400 <= r.status_code < 500


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"members": [123]},  # list item not an object
        {"members": [None]},
        {"members": [["nested", "list"]]},
        {"members": [{"age": 30}]},  # object without id
        {"members": [{"id": {"un": "hashable"}}]},  # non-string id
        {"members": [{"id": 7}]},
        {"income": [None]},
        {"income": [{"id": ["also", "unhashable"]}]},
        {"members": "not a list"},
        {"expenses": "not an object"},
        {"expenses": ["not", "an", "object"]},
    ],
)
async def test_degenerate_patch_shapes_are_422_not_500(client, patch):
    sid = await _new_session(client)
    r = await client.patch(f"/api/session/{sid}/household", json={"patch": patch})
    assert r.status_code == 422, f"{patch} -> {r.status_code}: {r.text}"
    assert "error" in r.json()["detail"]
    # The session survives and is untouched.
    assert (await _household(client, sid))["members"] == []


@pytest.mark.asyncio
async def test_oversized_patch_completes_coherently(client):
    sid = await _new_session(client)
    members = [{"id": f"m{i}", "age": 30} for i in range(2000)]
    r = await client.patch(f"/api/session/{sid}/household", json={"patch": {"members": members}})
    assert r.status_code == 200
    assert len(r.json()["household"]["members"]) == 2000
    # Session still serviceable afterwards.
    r2 = await client.get(f"/api/session/{sid}/report")
    assert r2.status_code == 200


@pytest.mark.asyncio
async def test_giant_string_field_does_not_crash(client):
    sid = await _new_session(client)
    r = await client.patch(
        f"/api/session/{sid}/household", json={"patch": {"county": "A" * 1_000_000}}
    )
    # Coherent 200 (the model has no length bound) — the key claim is no 500
    # and the session stays alive.
    assert r.status_code == 200
    assert (await _household(client, sid))["county"] == "A" * 1_000_000


# ---------------------------------------------------------------------------
# Unknown fields, duplicate ids, deletes of ghosts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch",
    [
        {"bogus_top_level": 1},
        {"members": [{"id": "m1", "ssn": "123-45-6789"}]},
        {"income": [{"id": "i1", "amount_dollars": 100}]},  # not a real field
        {"expenses": {"rent": 900}},  # misspelled expense key
    ],
)
async def test_unknown_fields_are_422_and_do_not_half_apply(client, patch):
    sid = await _new_session(client)
    r = await client.patch(f"/api/session/{sid}/household", json={"patch": patch})
    assert r.status_code == 422
    hh = await _household(client, sid)
    assert hh["members"] == [] and hh["income"] == []


@pytest.mark.asyncio
async def test_duplicate_ids_within_one_patch_merge_coherently(client):
    sid = await _new_session(client)
    patch = {"members": [{"id": "m1", "age": 3}, {"id": "m1", "age": 4}]}
    r = await client.patch(f"/api/session/{sid}/household", json={"patch": patch})
    # Merge-by-id semantics: the second entry updates the first; never a 500
    # and never two members with the same id.
    assert r.status_code == 200
    members = r.json()["household"]["members"]
    assert [m["id"] for m in members] == ["m1"]
    assert members[0]["age"] == 4


@pytest.mark.asyncio
async def test_delete_of_nonexistent_id_is_a_silent_noop(client):
    sid = await _new_session(client)
    r = await client.patch(
        f"/api/session/{sid}/household",
        json={"patch": {"members": [{"id": "ghost", "_delete": True}]}},
    )
    assert r.status_code == 200
    assert r.json()["household"]["members"] == []


# ---------------------------------------------------------------------------
# Validation failures must not half-apply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_patch_never_half_applies(client):
    sid = await _new_session(client)
    # Valid member AND invalid member in the same patch: all-or-nothing.
    patch = {
        "members": [{"id": "m1", "age": 30}, {"id": "m2", "age": 130}],
        "county": "Wake",
    }
    r = await client.patch(f"/api/session/{sid}/household", json={"patch": patch})
    assert r.status_code == 422
    assert "age" in r.json()["detail"]["error"]
    hh = await _household(client, sid)
    assert hh["members"] == [], "valid sibling from a failed patch leaked in"
    assert hh["county"] is None, "scalar from a failed patch leaked in"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "patch, field",
    [
        ({"members": [{"id": "m1", "age": 130}]}, "age"),
        ({"members": [{"id": "m1", "age": -1}]}, "age"),
        ({"income": [{"id": "i1", "amount": -5}]}, "amount_cents"),
        ({"expenses": {"rent_or_mortgage": -1}}, "rent_or_mortgage_cents"),
        ({"members": [{"id": "m1", "relationship": "cousin"}]}, "relationship"),
        ({"income": [{"id": "i1", "frequency": "fortnightly"}]}, "frequency"),
    ],
)
async def test_model_validation_failures_are_422_with_field_in_error(client, patch, field):
    sid = await _new_session(client)
    r = await client.patch(f"/api/session/{sid}/household", json={"patch": patch})
    assert r.status_code == 422
    assert field in r.json()["detail"]["error"]


# ---------------------------------------------------------------------------
# Unknown and stale session ids
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sid",
    # Path-traversal-shaped ids are excluded: httpx resolves "../" client-side
    # before the request is sent, so they never reach the router as a session id.
    ["nope", "0" * 32, "a b c", "ＵＮＩＣＯＤＥ", "'; DROP TABLE sessions;--"],
)
async def test_unknown_session_ids_404_everywhere(client, sid):
    for method, path, kwargs in [
        ("get", f"/api/session/{sid}/report", {}),
        ("patch", f"/api/session/{sid}/household", {"json": {"patch": {}}}),
        ("post", f"/api/session/{sid}/message", {"json": {"message": "hi"}}),
    ]:
        r = await getattr(client, method)(path, **kwargs)
        assert r.status_code == 404, f"{method} {path} -> {r.status_code}"


@pytest.mark.asyncio
async def test_stale_session_404s_after_ttl(monkeypatch):
    _set_settings_override(_make_settings(anthropic_api_key="key", session_ttl_minutes=1))
    clock = _clock()
    store = _reset_store(now=clock)
    _reset_budget(now_fn=clock)
    session = store.create()
    clock.advance(minutes=2)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.patch(f"/api/session/{session.id}/household", json={"patch": {"county": "Wake"}})
        assert r.status_code == 404
        r2 = await c.post(f"/api/session/{session.id}/message", json={"message": "hi"})
        assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Concurrency: a panel PATCH racing an in-flight chat message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_racing_inflight_message_leaves_session_coherent(client, monkeypatch):
    chat_started = asyncio.Event()
    release_chat = asyncio.Event()

    async def slow_run_turn(state, message, *, client=None, model="x", max_tokens=2048):
        yield TextEvent(delta="Recording that…")
        chat_started.set()
        await release_chat.wait()  # hold the stream open while the PATCH lands
        # The chat turn records its own fact mid-stream, like a tool dispatch.
        from interview.tools import dispatch

        dispatch(state, "update_household", {"patch": {"members": [{"id": "m1", "age": 40}]}})
        yield HouseholdEvent(data=state.household.model_dump())
        yield DoneEvent()

    monkeypatch.setattr(routes_module, "_run_turn", slow_run_turn)
    sid = await _new_session(client)

    async def send_message():
        return await client.post(f"/api/session/{sid}/message", json={"message": "he is 40"})

    async def send_patch():
        await chat_started.wait()
        r = await client.patch(f"/api/session/{sid}/household", json={"patch": {"county": "Wake"}})
        release_chat.set()
        return r

    msg_response, patch_response = await asyncio.gather(send_message(), send_patch())

    assert msg_response.status_code == 200
    assert patch_response.status_code == 200
    # Both writes survive: the panel's county and the chat's member.
    hh = await _household(client, sid)
    assert hh["county"] == "Wake"
    assert [m["id"] for m in hh["members"]] == ["m1"]
    assert hh["members"][0]["age"] == 40
