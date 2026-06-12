"""Tests for interview.loop.run_turn using a scripted fake Anthropic client.

No network. The fake client yields scripted stream events and exposes
get_final_message(), mirroring anthropic.AsyncAnthropic().messages.stream(...).
"""

from __future__ import annotations

from types import SimpleNamespace

import anthropic
import pytest

from interview.loop import API_ERROR_MESSAGE, run_turn
from interview.tools import SessionState
from rules.models import Household, Member

# ---------------------------------------------------------------------------
# Fake stream primitives
# ---------------------------------------------------------------------------


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_use_block(tool_id: str, name: str, tool_input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


class FakeStream:
    """Async context manager mirroring messages.stream(...)."""

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
                # stream the text out as a single text_delta event
                yield SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(type="text_delta", text=block.text),
                )

    async def get_final_message(self):
        return SimpleNamespace(content=self._blocks, stop_reason=self._stop_reason)


class FakeMessages:
    def __init__(self, scripted: list[tuple[list, str]]):
        # scripted: list of (blocks, stop_reason) — one per stream() call
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        blocks, stop_reason = self._scripted.pop(0)
        return FakeStream(blocks, stop_reason)


class FakeClient:
    def __init__(self, scripted: list[tuple[list, str]]):
        self.messages = FakeMessages(scripted)


class RaisingMessages:
    def __init__(self, exc: Exception):
        self._exc = exc
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        self.calls.append(kwargs)
        raise self._exc


class RaisingClient:
    def __init__(self, exc: Exception):
        self.messages = RaisingMessages(exc)


async def collect(state, user_message, *, client, model="claude-x"):
    return [e async for e in run_turn(state, user_message, client=client, model=model)]


# Shared patch fixtures (kept short to satisfy the 120-char line limit).
_AGE_35 = {"patch": {"members": [{"id": "m1", "age": 35}]}}
_AGE_999 = {"patch": {"members": [{"id": "m1", "age": 999}]}}


# ---------------------------------------------------------------------------
# Happy path: text → tool_use(update_household) → text → end_turn
# ---------------------------------------------------------------------------


@pytest.fixture
def state_with_member():
    return SessionState(household=Household(members=[Member(id="m1")]))


async def test_event_order_text_household_screening_text_done(state_with_member):
    client = FakeClient(
        [
            (
                [
                    text_block("Let me record that. "),
                    tool_use_block("tu1", "update_household", _AGE_35),
                ],
                "tool_use",
            ),
            ([text_block("Done — recorded their age.")], "end_turn"),
        ]
    )
    events = await collect(state_with_member, "The client is 35.", client=client)
    types = [e.type for e in events]
    assert types == ["text", "household", "screening", "text", "done"]
    # household event carries full model_dump
    hh_event = next(e for e in events if e.type == "household")
    assert hh_event.data["members"][0]["age"] == 35
    sc_event = next(e for e in events if e.type == "screening")
    assert "programs" in sc_event.data
    # state updated
    assert state_with_member.household.members[0].age == 35


async def test_tool_result_appended_to_history(state_with_member):
    client = FakeClient(
        [
            ([tool_use_block("tu1", "update_household", _AGE_35)], "tool_use"),
            ([text_block("ok")], "end_turn"),
        ]
    )
    await collect(state_with_member, "35 years old.", client=client)
    msgs = state_with_member.messages
    # user, assistant(tool_use), user(tool_result), assistant(text)
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert any(b["type"] == "tool_use" for b in msgs[1]["content"])
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0]["type"] == "tool_result"
    assert msgs[2]["content"][0]["tool_use_id"] == "tu1"
    assert msgs[3]["role"] == "assistant"


async def test_system_prompt_rebuilt_with_updated_summary(state_with_member):
    client = FakeClient(
        [
            ([tool_use_block("tu1", "update_household", _AGE_35)], "tool_use"),
            ([text_block("ok")], "end_turn"),
        ]
    )
    await collect(state_with_member, "35.", client=client)
    # Two stream() calls; the second system prompt reflects age=35 already recorded.
    calls = client.messages.calls
    assert len(calls) == 2
    second_system = calls[1]["system"]
    # age is recorded, so it should no longer appear as a missing field path
    assert "members[m1].age" not in second_system


async def test_no_tool_use_just_text(state_with_member):
    client = FakeClient([([text_block("What is the client's age?")], "end_turn")])
    events = await collect(state_with_member, "Hi", client=client)
    assert [e.type for e in events] == ["text", "done"]


# ---------------------------------------------------------------------------
# Validation error from tool: no household/screening events emitted
# ---------------------------------------------------------------------------


async def test_tool_validation_error_no_household_event(state_with_member):
    client = FakeClient(
        [
            ([tool_use_block("tu1", "update_household", _AGE_999)], "tool_use"),
            ([text_block("Hmm, let me reconsider.")], "end_turn"),
        ]
    )
    events = await collect(state_with_member, "Age 999.", client=client)
    types = [e.type for e in events]
    assert "household" not in types
    assert "screening" not in types
    assert types[-1] == "done"
    # tool_result still appended (with the error) so the loop can continue
    tool_result_msg = state_with_member.messages[2]
    assert "error" in tool_result_msg["content"][0]["content"]


# ---------------------------------------------------------------------------
# API error path
# ---------------------------------------------------------------------------


async def test_api_error_single_error_event_no_done(state_with_member):
    client = RaisingClient(anthropic.APIConnectionError(request=None))
    events = await collect(state_with_member, "Hello", client=client)
    assert len(events) == 1
    assert events[0].type == "error"
    assert events[0].message == API_ERROR_MESSAGE


async def test_api_error_rolls_back_failed_user_message(state_with_member):
    client = RaisingClient(anthropic.APIConnectionError(request=None))
    await collect(state_with_member, "Hello", client=client)
    # The failed user message must not corrupt history: it is removed.
    assert all(m.get("content") != "Hello" for m in state_with_member.messages)
    assert state_with_member.messages == []
    # State still usable: household intact.
    assert state_with_member.household.members[0].id == "m1"


async def test_api_error_midloop_after_tool(state_with_member):
    # First stream succeeds with a tool_use, second stream raises.
    class MixedMessages:
        def __init__(self):
            self.calls = []
            self._n = 0

        def stream(self, **kwargs):
            self.calls.append(kwargs)
            self._n += 1
            if self._n == 1:
                return FakeStream(
                    [tool_use_block("tu1", "update_household", _AGE_35)],
                    "tool_use",
                )
            raise anthropic.APIConnectionError(request=None)

    class MixedClient:
        def __init__(self):
            self.messages = MixedMessages()

    client = MixedClient()
    events = await collect(state_with_member, "35.", client=client)
    types = [e.type for e in events]
    assert types[-1] == "error"
    assert "done" not in types
    # History rolled back to before the failed turn (empty, since this was turn 1).
    assert state_with_member.messages == []


# ---------------------------------------------------------------------------
# History cap
# ---------------------------------------------------------------------------


async def test_history_cap_trims_to_50_no_dangling_tool_blocks():
    state = SessionState(household=Household(members=[Member(id="m1")]))
    # Seed 52 messages as 26 clean user/assistant turn-pairs (no tool blocks).
    for i in range(26):
        state.messages.append({"role": "user", "content": f"q{i}"})
        state.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"a{i}"}]})
    assert len(state.messages) == 52

    client = FakeClient([([text_block("ok")], "end_turn")])
    await collect(state, "new question", client=client)

    # After the turn: trimmed to <= 50 at a turn boundary.
    assert len(state.messages) <= 50
    # First message is a genuine user turn-start (not a tool_result).
    first = state.messages[0]
    assert first["role"] == "user"
    content = first["content"]
    if isinstance(content, list):
        assert not any(b.get("type") == "tool_result" for b in content)


async def test_history_cap_never_splits_tool_pair():
    state = SessionState(household=Household(members=[Member(id="m1")]))
    # Build turns where each turn is: user, assistant(tool_use), user(tool_result), assistant(text)
    for i in range(13):  # 13 * 4 = 52 messages
        state.messages.append({"role": "user", "content": f"q{i}"})
        state.messages.append(
            {"role": "assistant", "content": [{"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]}
        )
        state.messages.append(
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"t{i}", "content": "{}"}]}
        )
        state.messages.append({"role": "assistant", "content": [{"type": "text", "text": f"a{i}"}]})
    assert len(state.messages) == 52

    client = FakeClient([([text_block("ok")], "end_turn")])
    await collect(state, "new", client=client)

    assert len(state.messages) <= 50
    # First message must be a real user turn-start, not a dangling tool_result.
    first = state.messages[0]
    assert first["role"] == "user"
    assert isinstance(first["content"], str) or not any(
        b.get("type") == "tool_result" for b in first["content"]
    )
