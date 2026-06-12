"""FastAPI route handlers for the NC Benefits Navigator API.

All errors are returned as JSON ``{"error": "<message>"}`` with an appropriate
HTTP status code.

Test seam for the message endpoint
-----------------------------------
``run_turn`` is imported at the top of this module and stored as
``_run_turn``.  Tests monkeypatch ``server.routes._run_turn`` to inject a
fake async-generator without touching the real Anthropic client.  This keeps
the seam at the routes boundary (where the API key / model are resolved) and
avoids needing to pass a fake through the full call chain.

Token estimation
----------------
The SSE message endpoint estimates token counts from character counts using
the rough heuristic ``chars / 4 ≈ tokens``.  Exact usage is not available
from all streaming paths without buffering the entire response.  The estimate
is deliberately conservative (under-counts) so the budget guard is a safety
net rather than a precision meter.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sse_starlette.sse import EventSourceResponse

from interview.loop import run_turn as _real_run_turn
from interview.tools import _convert_patch_money, compact_screening
from rules.engine import screen_all
from rules.models import apply_patch
from server.config import get_settings
from server.sessions import BudgetExceeded, Session, charge, get_store, would_exceed

router = APIRouter()

# Test seam: tests replace this with a fake async-generator factory.
_run_turn = _real_run_turn


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class MessageBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class PatchBody(BaseModel):
    patch: dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error(msg: str, status: int) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": msg})


def _compact(session: Session) -> dict:
    if session.screening is None:
        session.screening = screen_all(session.household)
    return compact_screening(session.screening)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/healthz")
async def healthz():
    return {"ok": True}


@router.post("/api/session", status_code=201)
async def create_session():
    store = get_store()
    session = store.create()
    return {
        "session_id": session.id,
        "screening": _compact(session),
    }


@router.delete("/api/session/{session_id}", status_code=204)
async def delete_session(session_id: str):
    store = get_store()
    store.delete(session_id)
    return Response(status_code=204)


@router.get("/api/session/{session_id}/report")
async def get_report(session_id: str):
    store = get_store()
    try:
        session = store.get(session_id)
    except KeyError:
        raise _error("session not found", 404)

    if session.screening is None:
        session.screening = screen_all(session.household)

    return {
        "household": session.household.model_dump(),
        "screening": session.screening.model_dump(),
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.patch("/api/session/{session_id}/household")
async def patch_household(session_id: str, body: PatchBody):
    store = get_store()
    try:
        session = store.get(session_id)
    except KeyError:
        raise _error("session not found", 404)

    patch = _convert_patch_money(body.patch)
    try:
        new_household = apply_patch(session.household, patch)
    except PydanticValidationError as exc:
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(p) for p in first.get("loc", ())) or "<root>"
            msg = first.get("msg", "invalid")
            raise HTTPException(status_code=422, detail={"error": f"{loc}: {msg}"})
        raise HTTPException(status_code=422, detail={"error": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"error": str(exc)})

    screening = screen_all(new_household)
    session.household = new_household
    session.screening = screening

    return {
        "household": new_household.model_dump(),
        "screening": compact_screening(screening),
    }


@router.post("/api/session/{session_id}/message")
async def post_message(session_id: str, body: MessageBody, request: Request):
    settings = get_settings()

    # --- Guard: API key ---
    if not settings.anthropic_api_key:
        raise _error("AI assistant not configured — set ANTHROPIC_API_KEY", 503)

    store = get_store()
    try:
        session = store.get(session_id)
    except KeyError:
        raise _error("session not found", 404)

    # --- Guard: message limit ---
    if session.message_count >= settings.max_messages_per_session:
        raise _error("message limit reached", 429)

    # --- Guard: budget pre-check ---
    # Estimate input tokens roughly (system ~1000 chars + history + message)
    history_chars = sum(
        len(json.dumps(m)) for m in session.messages
    )
    est_input_tokens = (1000 + history_chars + len(body.message)) // 4
    est_output_tokens = 512  # conservative guess before streaming
    if would_exceed(est_input_tokens, est_output_tokens):
        raise _error("daily demo budget exhausted", 429)

    # Increment message count immediately (before stream starts).
    session.message_count += 1

    import anthropic as _anthropic

    client = _anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    state = session.as_interview_state()

    async def event_generator() -> AsyncIterator[dict]:
        output_text_chars = 0
        try:
            async for event in _run_turn(
                state,
                body.message,
                client=client,
                model=settings.model,
            ):
                event_data = event.model_dump()
                # Accumulate output chars for budget estimation.
                if event.type == "text":
                    output_text_chars += len(event.delta)
                yield {
                    "event": event.type,
                    "data": json.dumps(event_data),
                }
        finally:
            # Charge tokens after stream completes (best-effort; rough estimate).
            out_tokens = max(output_text_chars // 4, 1)
            try:
                charge(est_input_tokens, out_tokens)
            except BudgetExceeded:
                pass  # already over — logged by the guard; don't crash

    return EventSourceResponse(event_generator())
