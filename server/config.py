"""Application settings read from environment variables (prefix NAV_).

No pydantic-settings dependency — plain os.environ parsing in a frozen dataclass.
Falls back to bare ANTHROPIC_API_KEY when NAV_ANTHROPIC_API_KEY is absent.

Usage::

    from server.config import get_settings
    s = get_settings()
    s.model           # "claude-sonnet-4-6"
    s.anthropic_api_key  # "" if not configured (server still boots)

Pricing constants reflect claude-sonnet-4-6 public prices; update when pricing changes:
  Input:  $3.00 / MTok  → price_in_per_mtok  = 3.0
  Output: $15.00 / MTok → price_out_per_mtok = 15.0
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool_env(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str
    model: str
    session_ttl_minutes: int
    max_messages_per_session: int
    daily_budget_usd: float
    demo_mode: bool
    port: int
    # Pricing for rough token-cost estimation (claude-sonnet-4-6 public prices).
    price_in_per_mtok: float
    price_out_per_mtok: float


# Module-level cache; replaced by _override in tests.
_cached: Settings | None = None
_override: Settings | None = None


def get_settings() -> Settings:
    """Return the cached Settings instance, building it from env if needed.

    Tests call _reset_settings() after monkeypatching os.environ, or use
    _set_settings_override() for direct injection without touching env.
    """
    global _cached
    if _override is not None:
        return _override
    if _cached is None:
        _cached = _build_settings()
    return _cached


def _build_settings() -> Settings:
    api_key = (
        os.environ.get("NAV_ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    )
    model = os.environ.get("NAV_MODEL", "claude-sonnet-4-6")
    ttl = int(os.environ.get("NAV_SESSION_TTL_MINUTES", "60"))
    max_msg = int(os.environ.get("NAV_MAX_MESSAGES_PER_SESSION", "40"))
    budget = float(os.environ.get("NAV_DAILY_BUDGET_USD", "10.0"))
    demo = _bool_env("NAV_DEMO_MODE", default=False)
    port = int(os.environ.get("NAV_PORT", "8000"))
    price_in = float(os.environ.get("NAV_PRICE_IN_PER_MTOK", "3.0"))
    price_out = float(os.environ.get("NAV_PRICE_OUT_PER_MTOK", "15.0"))
    return Settings(
        anthropic_api_key=api_key,
        model=model,
        session_ttl_minutes=ttl,
        max_messages_per_session=max_msg,
        daily_budget_usd=budget,
        demo_mode=demo,
        port=port,
        price_in_per_mtok=price_in,
        price_out_per_mtok=price_out,
    )


# ---------------------------------------------------------------------------
# Test hooks
# ---------------------------------------------------------------------------


def _reset_settings() -> None:
    """Discard the cached instance so the next call re-reads env."""
    global _cached, _override
    _cached = None
    _override = None


def _set_settings_override(s: Settings) -> None:
    """Inject a Settings instance directly, bypassing env entirely."""
    global _override
    _override = s
