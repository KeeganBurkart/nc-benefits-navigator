"""Reusable fake Anthropic-client primitives for interview layer tests.

Import these in test_loop.py and any future test modules (e.g. server tests)
that need a scripted or error-raising Anthropic client without network access.
"""

from __future__ import annotations

from types import SimpleNamespace

from interview.loop import run_turn

# ---------------------------------------------------------------------------
# Block builders
# ---------------------------------------------------------------------------


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_use_block(tool_id: str, name: str, tool_input: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tool_id, name=name, input=tool_input)


# ---------------------------------------------------------------------------
# Fake stream / client
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Error-raising client
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helper: collect all events from a run_turn call
# ---------------------------------------------------------------------------


async def collect(state, user_message, *, client, model="claude-x"):
    return [e async for e in run_turn(state, user_message, client=client, model=model)]
