"""In-memory session store with TTL eviction and daily budget tracking.

Sessions compose with interview.SessionState (household, screening, messages).
The store is a plain dict; TTL sweeps happen on every access.

Budget guard
------------
A UTC-day-keyed cost accumulator lives at module level.  ``charge()`` raises
``BudgetExceeded`` when the running total for today crosses the configured
``daily_budget_usd``.  ``would_exceed()`` lets callers pre-check before
starting a streaming response.  The counter resets naturally when the UTC date
changes — no background task needed.

Injectable clock
----------------
``SessionStore`` accepts ``now: Callable[[], datetime]`` for deterministic
tests — advance the fake clock to trigger TTL expiry without real sleep.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from rules.engine import ScreeningResult, screen_all
from server.config import get_settings

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BudgetExceeded(Exception):
    """Raised when a charge would push the daily cost over the limit."""


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class Session:
    """One caseworker session.  Composes with interview.SessionState fields."""

    id: str
    # interview state fields
    household: object  # rules.models.Household — typed as object to avoid circular-ish imports at dataclass level
    screening: ScreeningResult | None
    messages: list[dict]
    # session metadata
    created_at: datetime
    last_active: datetime
    message_count: int = 0

    def as_interview_state(self) -> _SessionStateAdapter:
        """Return a SessionStateLike view that the interview loop can mutate."""
        return _SessionStateAdapter(self)


class _SessionStateAdapter:
    """Thin adapter so a Session can be passed wherever SessionStateLike is expected.

    Mutations go straight through to the parent Session.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def household(self):
        return self._session.household

    @household.setter
    def household(self, value):
        self._session.household = value

    @property
    def screening(self):
        return self._session.screening

    @screening.setter
    def screening(self, value):
        self._session.screening = value

    @property
    def messages(self) -> list[dict]:
        return self._session.messages

    @messages.setter
    def messages(self, value):
        self._session.messages = value


# ---------------------------------------------------------------------------
# Budget tracker
# ---------------------------------------------------------------------------


@dataclass
class _DayBudget:
    date_key: str  # UTC YYYY-MM-DD
    total_usd: float = 0.0


_day_budget = _DayBudget(date_key="")

# Module-level clock used by charge/would_exceed when no now_fn is passed.
# Tests override this via _set_budget_clock(); production code leaves it as-is.
_budget_clock: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def _set_budget_clock(fn: Callable[[], datetime]) -> None:
    """Inject a fake clock for the budget functions (test helper)."""
    global _budget_clock
    _budget_clock = fn


def _today_key(now_fn: Callable[[], datetime]) -> str:
    return now_fn().strftime("%Y-%m-%d")


def charge(input_tokens: int, output_tokens: int, *, now_fn: Callable[[], datetime] | None = None) -> None:
    """Add cost to today's running total; raise BudgetExceeded if limit hit.

    Token-to-USD conversion uses configured prices per MTok.
    """
    global _day_budget
    if now_fn is None:
        now_fn = _budget_clock
    settings = get_settings()
    today = _today_key(now_fn)
    if _day_budget.date_key != today:
        _day_budget = _DayBudget(date_key=today)
    cost = (input_tokens / 1_000_000) * settings.price_in_per_mtok + (
        output_tokens / 1_000_000
    ) * settings.price_out_per_mtok
    new_total = _day_budget.total_usd + cost
    if new_total > settings.daily_budget_usd:
        _day_budget.total_usd = new_total
        raise BudgetExceeded("daily demo budget exhausted")
    _day_budget.total_usd = new_total


def would_exceed(input_tokens: int, output_tokens: int, *, now_fn: Callable[[], datetime] | None = None) -> bool:
    """Return True if charging these tokens would push over the daily budget."""
    global _day_budget
    if now_fn is None:
        now_fn = _budget_clock
    settings = get_settings()
    today = _today_key(now_fn)
    if _day_budget.date_key != today:
        return False
    cost = (input_tokens / 1_000_000) * settings.price_in_per_mtok + (
        output_tokens / 1_000_000
    ) * settings.price_out_per_mtok
    return (_day_budget.total_usd + cost) > settings.daily_budget_usd


def _reset_budget(now_fn: Callable[[], datetime] | None = None) -> None:
    """Force-reset the day budget (test helper).

    Also resets the module-level budget clock if now_fn is provided.
    """
    global _day_budget, _budget_clock
    if now_fn is None:
        now_fn = _budget_clock
    else:
        _budget_clock = now_fn
    _day_budget = _DayBudget(date_key=_today_key(now_fn))


# ---------------------------------------------------------------------------
# Session store
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SessionStore:
    """Thread-safe-enough (GIL) in-memory session store.

    Parameters
    ----------
    now:
        Callable returning the current UTC datetime. Defaults to
        ``datetime.now(UTC)``.  Inject a fake clock in tests to simulate TTL
        expiry without sleeping.
    """

    def __init__(self, now: Callable[[], datetime] = _utcnow) -> None:
        self._sessions: dict[str, Session] = {}
        self._now = now

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_expired(self) -> None:
        """Remove sessions whose last_active is beyond TTL."""
        settings = get_settings()
        ttl_seconds = settings.session_ttl_minutes * 60
        cutoff = self._now().timestamp() - ttl_seconds
        expired = [
            sid
            for sid, sess in self._sessions.items()
            if sess.last_active.timestamp() < cutoff
        ]
        for sid in expired:
            del self._sessions[sid]

    def _is_expired(self, session: Session) -> bool:
        settings = get_settings()
        ttl_seconds = settings.session_ttl_minutes * 60
        return session.last_active.timestamp() < (self._now().timestamp() - ttl_seconds)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create(self) -> Session:
        """Create, store, and return a new Session."""
        self._evict_expired()
        from rules.models import Household

        now = self._now()
        session = Session(
            id=uuid.uuid4().hex,
            household=Household(),
            screening=screen_all(Household()),
            messages=[],
            created_at=now,
            last_active=now,
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session:
        """Return the session; raise KeyError if missing or expired (and evict)."""
        self._evict_expired()
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        if self._is_expired(session):
            del self._sessions[session_id]
            raise KeyError(session_id)
        session.last_active = self._now()
        return session

    def delete(self, session_id: str) -> None:
        """Delete a session if it exists (no-op if already gone)."""
        self._sessions.pop(session_id, None)

    def touch(self, session_id: str) -> None:
        """Update last_active without raising on missing session."""
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_active = self._now()


# ---------------------------------------------------------------------------
# Module-level default store (app uses this; tests inject their own)
# ---------------------------------------------------------------------------

_default_store: SessionStore | None = None


def get_store() -> SessionStore:
    global _default_store
    if _default_store is None:
        _default_store = SessionStore()
    return _default_store


def _reset_store(now: Callable[[], datetime] = _utcnow) -> SessionStore:
    """Replace (and return) the default store — used in tests."""
    global _default_store
    _default_store = SessionStore(now=now)
    return _default_store
