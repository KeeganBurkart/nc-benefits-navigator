"""Deterministic fake Anthropic client for E2E tests (NAV_FAKE_LLM=1).

Test infrastructure only — never used in production. Replays a canned
three-turn caseworker conversation that ends in a fully resolved screening,
so Playwright can drive the real server + UI without network access or an
API key.

The fake is stateless across requests: it decides what to return from the
shape of the incoming ``messages`` list (how many real user turns there are
and whether the last message is a tool_result), so it works with a fresh
client instance per HTTP request.
"""

from __future__ import annotations

from types import SimpleNamespace

from interview.prompt import DISCLAIMER_SENTENCE

_TURN_1_PATCH = {
    "county": "New Hanover",
    "purchases_and_prepares_together": True,
    "members": [
        {
            "id": "m1",
            "age": 34,
            "relationship": "self",
            "is_pregnant": False,
            "is_disabled": False,
            "immigration_status": "citizen",
            "is_student": False,
        }
    ],
    "income": [
        {
            "id": "i1",
            "member_id": "m1",
            "kind": "wages",
            "amount": 1200.50,
            "frequency": "monthly",
        }
    ],
}

_TURN_2_PATCH = {
    "expenses": {
        "rent_or_mortgage": 950,
        "utilities_included": False,
        "pays_heating_cooling": True,
        "dependent_care": 0,
        "child_support_paid": 0,
        "medical_expenses_elderly_disabled": 0,
    }
}

# Includes markdown so the E2E locks the chat renderer (bold, bullets, break).
_FINAL_SUMMARY = (
    "Here are the screening results:\n\n"
    "- FNS (Food and Nutrition Services / SNAP): **likely eligible**, with an "
    "estimated benefit shown in the results panel.\n"
    "- NC Medicaid: **likely eligible**.\n\n"
    "You can print the action plan for the client. "
    f"{DISCLAIMER_SENTENCE}"
)


def _text(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use(tool_id: str, name: str, tool_input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


class _FakeStream:
    def __init__(self, blocks: list, stop_reason: str):
        self._blocks = blocks
        self._stop_reason = stop_reason

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def __aiter__(self):
        for block in self._blocks:
            if block.type == "text":
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text=block.text),
                )

    async def get_final_message(self):
        return SimpleNamespace(content=self._blocks, stop_reason=self._stop_reason)


def _is_tool_result(msg: dict) -> bool:
    content = msg.get("content")
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


class _FakeMessages:
    def stream(self, **kwargs):
        messages = kwargs["messages"]
        turn = sum(
            1 for m in messages if m.get("role") == "user" and not _is_tool_result(m)
        )
        after_tool = _is_tool_result(messages[-1])

        if turn == 1:
            if not after_tool:
                return _FakeStream(
                    [
                        _text("Got it — recording the household now."),
                        _tool_use("fake_t1", "update_household", {"patch": _TURN_1_PATCH}),
                    ],
                    "tool_use",
                )
            return _FakeStream(
                [_text("Recorded. What is the monthly rent or mortgage payment?")],
                "end_turn",
            )
        if turn == 2:
            if not after_tool:
                return _FakeStream(
                    [
                        _text("Adding those housing costs."),
                        _tool_use("fake_t2", "update_household", {"patch": _TURN_2_PATCH}),
                    ],
                    "tool_use",
                )
            return _FakeStream(
                [_text("Thanks. Say anything else to see the final results.")],
                "end_turn",
            )
        if turn == 3:
            if not after_tool:
                return _FakeStream(
                    [_tool_use("fake_t3", "get_screening_status", {})],
                    "tool_use",
                )
            return _FakeStream([_text(_FINAL_SUMMARY)], "end_turn")
        return _FakeStream(
            [_text("The screening is complete — start a new screening to run another.")],
            "end_turn",
        )


class FakeLLMClient:
    """Drop-in for anthropic.AsyncAnthropic inside run_turn."""

    def __init__(self):
        self.messages = _FakeMessages()
