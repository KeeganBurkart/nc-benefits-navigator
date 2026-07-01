"""Real-API interview evals — excluded from the default run.

Run manually with a real key:

    ANTHROPIC_API_KEY=... uv run pytest -m eval -s

One scripted caseworker conversation runs ONCE against the live API (module
fixture); the five evals assert properties of the recorded transcript, so the
whole suite costs a single conversation (~10-20k tokens, well under $1).

Assertions target tool-call behavior and engine fidelity, not exact wording.
The re-ask check is a keyword heuristic on strong signals (age/county/rent/
wages), documented per check.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field

import anthropic
import pytest

from interview.loop import run_turn
from interview.prompt import DISCLAIMER_SENTENCE
from interview.tools import SessionState

pytestmark = pytest.mark.eval

MODEL = os.environ.get("NAV_MODEL", "claude-sonnet-4-6")
PRICE_IN_PER_MTOK = 3.0
PRICE_OUT_PER_MTOK = 15.0

SCRIPT = [
    (
        "New client: single mom, 32 years old, US citizen, not pregnant, not disabled, "
        "not a student. Two kids ages 4 and 7, both citizens, neither pregnant nor "
        "disabled, not students."
    ),
    "Everyone buys and prepares food together. They live in New Hanover County.",
    (
        "She earns $1,400 a month in wages. The kids have no income — "
        "that is the household's only income."
    ),
    (
        "Rent is $900 a month, utilities not included, and she pays for heating. "
        "No child care costs, no child support paid out, no medical expenses."
    ),
    "That's everything — what are the results?",
]

# If the model still needs facts after the script, answer by missing-field leaf.
FOLLOWUP_ANSWERS = {
    "is_pregnant": "No one in the household is pregnant.",
    "is_disabled": "No one has a disability.",
    "is_student": "No one is a student.",
    "immigration_status": "Everyone is a US citizen.",
    "relationship": "The mom is the applicant; the two kids are her children.",
    "age": "The mom is 32; the kids are 4 and 7.",
    "county": "New Hanover County.",
    "purchases_and_prepares_together": "Yes, everyone buys and prepares food together.",
}
MAX_FOLLOWUPS = 4


# ---------------------------------------------------------------------------
# Token counting wrapper
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
# Transcript
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


async def _run_script() -> Transcript:
    state = SessionState()
    client = CountingClient()
    transcript = Transcript()

    for message in SCRIPT:
        transcript.turns.append(await _send(state, client, message))

    followups = 0
    while _missing(state) and followups < MAX_FOLLOWUPS:
        leaf = _missing(state)[0].split(".")[-1]
        answer = FOLLOWUP_ANSWERS.get(leaf, "I don't have that — assume the most common case.")
        transcript.turns.append(await _send(state, client, answer))
        followups += 1

    transcript.final_state = state
    transcript.cost_usd = client.cost_usd
    transcript.input_tokens = client.input_tokens
    transcript.output_tokens = client.output_tokens
    return transcript


@pytest.fixture(scope="module")
def transcript() -> Transcript:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("NAV_ANTHROPIC_API_KEY")):
        pytest.skip("eval suite needs ANTHROPIC_API_KEY")
    result = asyncio.run(_run_script())
    print(
        f"\n[eval cost] {result.input_tokens} in / {result.output_tokens} out tokens "
        f"= ${result.cost_usd:.4f} ({len(result.turns)} turns)"
    )
    assert result.cost_usd < 1.0, "eval suite exceeded the $1 budget"
    return result


# ---------------------------------------------------------------------------
# Evals
# ---------------------------------------------------------------------------


def test_stated_facts_patched_within_next_turn(transcript: Transcript):
    # Turn 1 states three members; the patch must land during that same turn.
    assert transcript.turns[0].members_after >= 3


def test_never_reasks_recorded_fact(transcript: Transcript):
    # Keyword heuristic on strong signals. After the script turn that records a
    # fact, later assistant questions must not ask for it again.
    signals = {
        1: ["how old", "what age", "ages of"],  # ages recorded in turn 1
        2: ["which county", "what county"],  # county recorded in turn 2
        3: ["how much does she earn", "how much income", "what is her income"],
        4: ["what is the rent", "how much is the rent", "how much is rent"],
    }
    for recorded_turn, phrases in signals.items():
        for later in transcript.turns[recorded_turn:]:
            text = later.assistant_text.lower()
            for phrase in phrases:
                assert phrase not in text, (
                    f"re-asked a recorded fact ({phrase!r}) after turn {recorded_turn}: "
                    f"{later.assistant_text!r}"
                )


def test_no_verdict_contradiction_and_engine_numbers(transcript: Transcript):
    state = transcript.final_state
    assert state is not None and state.screening is not None
    final_text = transcript.turns[-1].assistant_text.lower()

    statuses = {p.program: p.status for p in state.screening.programs}
    if all(s == "likely_eligible" for s in statuses.values()):
        assert "not eligible" not in final_text
        assert "ineligible" not in final_text

    fns = next(p for p in state.screening.programs if p.program == "fns")
    if fns.estimated_benefit_cents is not None:
        whole_dollars = str(fns.estimated_benefit_cents // 100)
        assert whole_dollars in transcript.turns[-1].assistant_text, (
            f"final summary missing engine benefit (${whole_dollars}): "
            f"{transcript.turns[-1].assistant_text!r}"
        )


def test_one_question_per_turn(transcript: Transcript):
    # Interview turns (all but the final summary) should ask one question; the
    # contract allows <=2 '?' for phrasing slack.
    for turn in transcript.turns[:-1]:
        assert turn.assistant_text.count("?") <= 2, (
            f"asked multiple questions in one turn: {turn.assistant_text!r}"
        )


def test_happy_path_resolves_with_disclaimer(transcript: Transcript):
    state = transcript.final_state
    assert state is not None and state.screening is not None
    assert state.screening.missing_fields == []
    for program in state.screening.programs:
        assert program.status != "needs_more_info"
    assert DISCLAIMER_SENTENCE in transcript.turns[-1].assistant_text
