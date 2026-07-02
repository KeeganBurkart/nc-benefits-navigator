"""Shared machinery for the real-API interview evals.

A Scenario is a scripted caseworker conversation; run_scenario() drives it
through interview.loop.run_turn against the live API and returns a Transcript
the eval tests assert on. Token usage is accumulated module-wide so the suite
can print one cost line and enforce the $1 budget.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import anthropic
import pytest

from interview.loop import run_turn
from interview.tools import SessionState

MODEL = os.environ.get("NAV_MODEL", "claude-sonnet-4-6")
PRICE_IN_PER_MTOK = 3.0
PRICE_OUT_PER_MTOK = 15.0

# If the model still needs facts after a script, answer by missing-field leaf.
FOLLOWUP_ANSWERS = {
    "is_pregnant": "No one in the household is pregnant.",
    "is_disabled": "No one has a disability.",
    "is_student": "No one is a student.",
    "immigration_status": "Everyone is a US citizen.",
    "relationship": "The first person is the applicant; the others are their children.",
    "age": "Use the ages I gave you.",
    "county": "New Hanover County.",
    "purchases_and_prepares_together": "Yes, everyone buys and prepares food together.",
    "rent_or_mortgage_cents": "Rent is $800 a month.",
    "utilities_included": "Utilities are not included.",
    "pays_heating_cooling": "They pay for heating.",
    "dependent_care_cents": "No dependent care costs.",
    "child_support_paid_cents": "No child support paid out.",
    "medical_expenses_elderly_disabled_cents": "No medical expenses.",
}


# ---------------------------------------------------------------------------
# Token counting client
# ---------------------------------------------------------------------------


class _CountingStream:
    def __init__(self, inner_cm, counter):
        self._inner_cm = inner_cm
        self._counter = counter
        self._stream = None

    async def __aenter__(self):
        self._stream = await self._inner_cm.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._inner_cm.__aexit__(*exc)

    def __aiter__(self):
        return self._stream.__aiter__()

    async def get_final_message(self):
        msg = await self._stream.get_final_message()
        self._counter.input_tokens += msg.usage.input_tokens
        self._counter.output_tokens += msg.usage.output_tokens
        return msg


class CountingClient:
    """Wraps AsyncAnthropic, summing usage across every stream call."""

    def __init__(self):
        self._client = anthropic.AsyncAnthropic()
        self.input_tokens = 0
        self.output_tokens = 0
        self.messages = self

    def stream(self, **kwargs):
        return _CountingStream(self._client.messages.stream(**kwargs), self)

    @property
    def cost_usd(self) -> float:
        return (
            self.input_tokens * PRICE_IN_PER_MTOK
            + self.output_tokens * PRICE_OUT_PER_MTOK
        ) / 1_000_000


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    user_message: str
    assistant_text: str
    missing_before: list[str]
    missing_after: list[str]
    members_after: int


@dataclass
class Transcript:
    turns: list[Turn] = field(default_factory=list)
    final_state: SessionState | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def final_text(self) -> str:
        return self.turns[-1].assistant_text

    def statuses(self) -> dict[str, str]:
        assert self.final_state is not None and self.final_state.screening is not None
        return {p.program: p.status for p in self.final_state.screening.programs}


def _missing(state: SessionState) -> list[str]:
    if state.screening is None:
        return ["<no screening yet>"]
    return list(state.screening.missing_fields)


async def _send(state: SessionState, client, message: str) -> Turn:
    missing_before = _missing(state)
    text_parts: list[str] = []
    async for event in run_turn(state, message, client=client, model=MODEL):
        if event.type == "text":
            text_parts.append(event.delta)
        elif event.type == "error":
            pytest.fail(f"API error during eval: {event.message}")
    return Turn(
        user_message=message,
        assistant_text="".join(text_parts),
        missing_before=missing_before,
        missing_after=_missing(state),
        members_after=len(state.household.members),
    )


async def run_scenario(
    script: list[str],
    *,
    followups: bool = True,
    max_followups: int = 4,
) -> Transcript:
    """Run one scripted conversation against the live API.

    With followups=True, unanswered missing fields after the script are
    answered from FOLLOWUP_ANSWERS until resolved (or max_followups hit).
    """
    state = SessionState()
    client = CountingClient()
    transcript = Transcript()

    for message in script:
        transcript.turns.append(await _send(state, client, message))

    sent = 0
    while followups and _missing(state) and sent < max_followups:
        leaf = _missing(state)[0].split(".")[-1]
        answer = FOLLOWUP_ANSWERS.get(leaf, "I don't have that — assume the most common case.")
        transcript.turns.append(await _send(state, client, answer))
        sent += 1

    transcript.final_state = state
    transcript.cost_usd = client.cost_usd
    transcript.input_tokens = client.input_tokens
    transcript.output_tokens = client.output_tokens
    return transcript


def require_api_key() -> None:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("NAV_ANTHROPIC_API_KEY")):
        pytest.skip("eval suite needs ANTHROPIC_API_KEY")
