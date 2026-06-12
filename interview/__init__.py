"""Interview layer: LLM fact-extraction loop over the deterministic rules engine.

The LLM never decides eligibility. It interviews a caseworker, extracts facts
into structured patches, and relays what the rules engine returned.
"""

from interview.loop import (
    API_ERROR_MESSAGE,
    HISTORY_CAP,
    DoneEvent,
    ErrorEvent,
    Event,
    HouseholdEvent,
    ScreeningEvent,
    TextEvent,
    run_turn,
)
from interview.prompt import DISCLAIMER_SENTENCE, build_system_prompt
from interview.tools import (
    TOOLS,
    SessionState,
    SessionStateLike,
    compact_screening,
    dispatch,
)

__all__ = [
    "API_ERROR_MESSAGE",
    "HISTORY_CAP",
    "DISCLAIMER_SENTENCE",
    "TOOLS",
    "DoneEvent",
    "ErrorEvent",
    "Event",
    "HouseholdEvent",
    "ScreeningEvent",
    "SessionState",
    "SessionStateLike",
    "TextEvent",
    "build_system_prompt",
    "compact_screening",
    "dispatch",
    "run_turn",
]
