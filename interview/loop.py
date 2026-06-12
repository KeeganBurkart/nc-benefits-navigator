"""The tool-use agent loop: stream a turn, extract facts, relay screening.

``run_turn`` drives one caseworker turn end to end. It streams text deltas as
``text`` events, dispatches any ``update_household`` / ``get_screening_status``
tool calls, emits ``household`` + ``screening`` events after a successful
household update, feeds tool results back to the model, and loops until the
model ends its turn.

The model NEVER decides eligibility — it only relays what the deterministic
engine (rules/) returned via the tools in interview.tools.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Literal

from pydantic import BaseModel

from interview.prompt import build_system_prompt
from interview.tools import (
    TOOLS,
    SessionStateLike,
    compact_screening,
    dispatch,
)
from rules.engine import screen_all

# Maximum number of messages retained in history; older whole turns are dropped.
HISTORY_CAP = 50

# Shown to the caseworker when the model/API is unreachable. The household can
# still be edited directly, so the UI degrades gracefully.
API_ERROR_MESSAGE = (
    "The AI assistant is unreachable — you can keep editing the household facts directly."
)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


class TextEvent(BaseModel):
    type: Literal["text"] = "text"
    delta: str


class HouseholdEvent(BaseModel):
    type: Literal["household"] = "household"
    data: dict


class ScreeningEvent(BaseModel):
    type: Literal["screening"] = "screening"
    data: dict


class DoneEvent(BaseModel):
    type: Literal["done"] = "done"


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


# Tagged union. A turn emits zero or more text/household/screening events and
# terminates with EXACTLY ONE of:
#   - ``done``  on a clean end_turn, OR
#   - ``error`` if the Anthropic API was unreachable.
# An error terminates the stream INSTEAD of done — never both.
Event = TextEvent | HouseholdEvent | ScreeningEvent | DoneEvent | ErrorEvent


# ---------------------------------------------------------------------------
# History trimming
# ---------------------------------------------------------------------------


def _trim_history(messages: list[dict]) -> None:
    """Drop the oldest whole turns so ``messages`` is <= HISTORY_CAP, in place.

    A turn boundary is a ``user`` message whose content is NOT a tool_result
    (a fresh caseworker turn). Trimming only at such boundaries guarantees we
    never split a tool_use / tool_result pair: assistant tool_use blocks and
    the user tool_result that answers them always travel together.
    """
    if len(messages) <= HISTORY_CAP:
        return

    # Find indices of genuine turn starts (user messages that are not tool results).
    boundaries = [
        i
        for i, msg in enumerate(messages)
        if msg.get("role") == "user" and not _is_tool_result(msg)
    ]

    # Drop the earliest whole turns until we're within the cap, always cutting
    # at a turn boundary so no dangling tool blocks remain.
    for boundary in boundaries:
        if len(messages) - boundary <= HISTORY_CAP:
            del messages[:boundary]
            return

    # Fallback (should be unreachable): keep the last boundary's turn.
    if boundaries:
        del messages[: boundaries[-1]]


def _is_tool_result(msg: dict) -> bool:
    content = msg.get("content")
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        )
    return False


# ---------------------------------------------------------------------------
# run_turn
# ---------------------------------------------------------------------------


def _compact_summary_str(state: SessionStateLike) -> str:
    screening = state.screening if state.screening is not None else screen_all(state.household)
    return json.dumps(compact_screening(screening), indent=2)


async def run_turn(
    state: SessionStateLike,
    user_message: str,
    *,
    client=None,
    model: str,
    max_tokens: int = 2048,
) -> AsyncIterator[Event]:
    """Run one caseworker turn, yielding ``Event`` objects as they happen.

    Streams assistant text, dispatches tool calls, emits household/screening
    events after a successful update, and loops until the model ends its turn.

    On any Anthropic API error the failed user message is removed from history
    (history stays consistent and the session remains usable), a single
    ``error`` event is emitted, and the stream stops WITHOUT a ``done`` event.
    """
    if client is None:
        import anthropic

        client = anthropic.AsyncAnthropic()

    # Import here so a missing/odd anthropic install doesn't break import-time.
    import anthropic

    # Append the caseworker's message. Remember where, so we can roll it back on
    # API failure and keep history consistent.
    user_block = {"role": "user", "content": user_message}
    state.messages.append(user_block)
    _trim_history(state.messages)

    try:
        while True:
            system_prompt = build_system_prompt(_compact_summary_str(state))

            assistant_blocks: list[dict] = []
            async with client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=TOOLS,
                messages=state.messages,
            ) as stream:
                async for event in stream:
                    if (
                        event.type == "content_block_delta"
                        and getattr(event.delta, "type", None) == "text_delta"
                    ):
                        yield TextEvent(delta=event.delta.text)

                final_message = await stream.get_final_message()

            # Record the assistant turn verbatim (text + tool_use blocks).
            assistant_blocks = [_block_to_dict(b) for b in final_message.content]
            state.messages.append({"role": "assistant", "content": assistant_blocks})

            tool_uses = [b for b in final_message.content if b.type == "tool_use"]
            if final_message.stop_reason != "tool_use" or not tool_uses:
                break

            # Dispatch every tool_use block and collect tool_result blocks.
            tool_results: list[dict] = []
            for block in tool_uses:
                result_json = dispatch(state, block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_json,
                    }
                )
                if block.name == "update_household" and not _is_error_json(result_json):
                    yield HouseholdEvent(data=state.household.model_dump())
                    yield ScreeningEvent(data=state.screening.model_dump())

            state.messages.append({"role": "user", "content": tool_results})

        _trim_history(state.messages)
        yield DoneEvent()

    except (anthropic.APIError, anthropic.APIConnectionError):
        # Roll back the failed turn so history stays consistent and usable.
        # Drop everything appended at/after the caseworker's message.
        if user_block in state.messages:
            idx = state.messages.index(user_block)
            del state.messages[idx:]
        yield ErrorEvent(message=API_ERROR_MESSAGE)
        # No done event — error terminates the stream instead.


def _is_error_json(result_json: str) -> bool:
    try:
        parsed = json.loads(result_json)
    except (ValueError, TypeError):
        return False
    return isinstance(parsed, dict) and "error" in parsed


def _block_to_dict(block) -> dict:
    """Convert an Anthropic content block to a plain dict for message history."""
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    # Unknown block types: best-effort dump.
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return dict(block)
