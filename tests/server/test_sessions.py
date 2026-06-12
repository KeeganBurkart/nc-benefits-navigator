"""Tests for server/sessions.py: store lifecycle, TTL, budget guard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from server.config import Settings, _reset_settings, _set_settings_override
from server.sessions import (
    BudgetExceeded,
    SessionStore,
    _reset_budget,
    charge,
    would_exceed,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> Settings:
    base = dict(
        anthropic_api_key="",
        model="claude-sonnet-4-6",
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


@pytest.fixture(autouse=True)
def reset_config():
    """Ensure settings override is cleared after each test."""
    _reset_settings()
    yield
    _reset_settings()


@pytest.fixture()
def default_settings():
    s = _make_settings()
    _set_settings_override(s)
    return s


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


def _clock(hours: float = 0) -> FakeClock:
    return FakeClock(datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC) + timedelta(hours=hours))


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def test_create_returns_session(default_settings):
    store = SessionStore(now=_clock())
    session = store.create()
    assert session.id
    assert session.household is not None
    assert session.screening is not None
    assert session.messages == []
    assert session.message_count == 0


def test_get_returns_created_session(default_settings):
    store = SessionStore(now=_clock())
    s = store.create()
    fetched = store.get(s.id)
    assert fetched.id == s.id


def test_get_missing_raises_key_error(default_settings):
    store = SessionStore(now=_clock())
    with pytest.raises(KeyError):
        store.get("nonexistent-id")


def test_delete_removes_session(default_settings):
    store = SessionStore(now=_clock())
    s = store.create()
    store.delete(s.id)
    with pytest.raises(KeyError):
        store.get(s.id)


def test_delete_nonexistent_is_noop(default_settings):
    store = SessionStore(now=_clock())
    store.delete("ghost-id")  # must not raise


def test_multiple_sessions_independent(default_settings):
    store = SessionStore(now=_clock())
    a = store.create()
    b = store.create()
    assert a.id != b.id
    store.delete(a.id)
    # b still accessible
    assert store.get(b.id).id == b.id


# ---------------------------------------------------------------------------
# TTL eviction
# ---------------------------------------------------------------------------


def test_expired_session_raises_on_get(default_settings):
    s = _make_settings(session_ttl_minutes=1)
    _set_settings_override(s)
    clock = _clock()
    store = SessionStore(now=clock)
    sess = store.create()
    clock.advance(minutes=2)
    with pytest.raises(KeyError):
        store.get(sess.id)


def test_non_expired_session_accessible(default_settings):
    s = _make_settings(session_ttl_minutes=60)
    _set_settings_override(s)
    clock = _clock()
    store = SessionStore(now=clock)
    sess = store.create()
    clock.advance(minutes=30)
    assert store.get(sess.id).id == sess.id


def test_ttl_eviction_on_create(default_settings):
    s = _make_settings(session_ttl_minutes=1)
    _set_settings_override(s)
    clock = _clock()
    store = SessionStore(now=clock)
    old = store.create()
    clock.advance(minutes=2)
    # create triggers eviction sweep
    store.create()
    with pytest.raises(KeyError):
        store.get(old.id)


# ---------------------------------------------------------------------------
# Budget guard
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_budget(default_settings):
    clock = _clock()
    _reset_budget(now_fn=clock)
    yield
    _reset_budget(now_fn=clock)


def test_charge_does_not_raise_under_limit(default_settings):
    clock = _clock()
    _reset_budget(now_fn=clock)
    # 1 input MTok @ $3 = $3, well under $10
    charge(1_000_000, 0, now_fn=clock)


def test_charge_raises_over_limit(default_settings):
    clock = _clock()
    _reset_budget(now_fn=clock)
    # 1 output MTok @ $15 = $15 > $10
    with pytest.raises(BudgetExceeded):
        charge(0, 1_000_000, now_fn=clock)


def test_charge_accumulates(default_settings):
    clock = _clock()
    _reset_budget(now_fn=clock)
    # Two charges: $6 + $6 = $12 > $10 budget
    tokens_for_6 = int(6.0 / 3.0 * 1_000_000)  # $3/MTok input → 2 MTok = $6
    charge(tokens_for_6, 0, now_fn=clock)  # $6 — fine
    with pytest.raises(BudgetExceeded):
        charge(tokens_for_6, 0, now_fn=clock)  # $12 > $10 — trips


def test_charge_accumulates_correctly():
    """Precise accumulation test with custom prices."""
    s = _make_settings(daily_budget_usd=10.0, price_in_per_mtok=5.0)
    _set_settings_override(s)
    clock = _clock()
    _reset_budget(now_fn=clock)
    # 1 MTok @ $5/MTok = $5 — OK
    charge(1_000_000, 0, now_fn=clock)
    # Another 1.2 MTok @ $5 = $6 → total $11 > $10 — must raise
    with pytest.raises(BudgetExceeded):
        charge(1_200_000, 0, now_fn=clock)
    _reset_settings()


def test_budget_resets_on_date_change(default_settings):
    clock = _clock()
    _reset_budget(now_fn=clock)
    # Push close to limit (input $9 worth)
    tokens_9 = int(9.0 / 3.0 * 1_000_000)
    charge(tokens_9, 0, now_fn=clock)
    # Advance to next day
    clock.advance(hours=13)  # crosses midnight UTC
    # Now a big charge that would have exceeded yesterday is fine
    charge(tokens_9, 0, now_fn=clock)


def test_would_exceed_returns_true_when_over(default_settings):
    clock = _clock()
    _reset_budget(now_fn=clock)
    # Fill up almost all the budget
    tokens_9 = int(9.0 / 3.0 * 1_000_000)
    charge(tokens_9, 0, now_fn=clock)
    # Another $3 would push to $12
    assert would_exceed(1_000_000, 0, now_fn=clock) is True


def test_would_exceed_returns_false_when_under(default_settings):
    clock = _clock()
    _reset_budget(now_fn=clock)
    assert would_exceed(100, 100, now_fn=clock) is False


def test_would_exceed_false_on_new_day(default_settings):
    clock = _clock()
    _reset_budget(now_fn=clock)
    # Fill budget
    tokens_big = int(20.0 / 3.0 * 1_000_000)
    try:
        charge(tokens_big, 0, now_fn=clock)
    except BudgetExceeded:
        pass
    # New day: counter not for today, so would_exceed sees fresh slate
    clock.advance(hours=25)
    assert would_exceed(1_000_000, 0, now_fn=clock) is False
