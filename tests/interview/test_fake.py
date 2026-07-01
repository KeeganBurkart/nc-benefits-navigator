"""The canned fake-LLM conversation must drive run_turn to a resolved screening.

Guards the Playwright E2E infrastructure: if the fake drifts out of sync with
the tool schemas or loop protocol, this fails offline instead of in CI E2E.
"""

from __future__ import annotations

from interview.fake import FakeLLMClient
from interview.prompt import DISCLAIMER_SENTENCE
from interview.tools import SessionState

from tests.interview.fakes import collect


async def test_fake_conversation_reaches_resolved_screening():
    state = SessionState()
    client = FakeLLMClient()

    events1 = await collect(state, "Single adult, 34, works part time", client=client)
    assert [e.type for e in events1][-1] == "done"
    assert {m.id for m in state.household.members} == {"m1"}
    assert state.household.income[0].amount_cents == 120050  # dollars converted

    events2 = await collect(state, "Rent is 950, pays heating", client=client)
    assert [e.type for e in events2][-1] == "done"
    assert state.household.expenses.rent_or_mortgage_cents == 95000

    events3 = await collect(state, "That's everything", client=client)
    text = "".join(e.delta for e in events3 if e.type == "text")
    assert DISCLAIMER_SENTENCE in text

    assert state.screening is not None
    statuses = {p.program: p.status for p in state.screening.programs}
    assert statuses == {"fns": "likely_eligible", "medicaid": "likely_eligible"}
    assert state.screening.missing_fields == []

    # A fourth message past the script must not crash.
    events4 = await collect(state, "hello again", client=client)
    assert [e.type for e in events4][-1] == "done"
