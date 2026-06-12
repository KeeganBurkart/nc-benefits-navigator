# NC Benefits Navigator — Design Spec

**Date:** 2026-06-12
**Status:** Approved

## Purpose

An open-source, staff-facing benefits screener for North Carolina nonprofits with no IT staff. A caseworker uses it while sitting with a client: a conversational AI interview extracts household facts, a deterministic rules engine screens the household against **FNS (SNAP)** and **NC Medicaid**, and the output is a printable action plan — likely eligibility with cited reasons, an estimated FNS allotment, and a document checklist for the application.

This is also a calling-card project: the public demo deployment is the artifact that consulting outreach links to.

## Core principles

1. **The LLM never decides eligibility.** A deterministic, versioned, tested rules engine does the math. The LLM interviews, extracts structured facts, and explains results. This separation is the headline architectural feature.
2. **Nothing is stored.** Sessions are in-memory with TTL eviction; no database exists. This deletes the HIPAA/PII adoption barrier for orgs without IT.
3. **Every eligibility reason carries a citation** to the specific NC DHHS policy manual section (name + URL), attached as rule metadata — no RAG pipeline in v1.
4. **Screener, not determination.** Persistent UI disclaimer; results always link to ePASS for official application.
5. **Adoptable without help.** One Docker container, one README, docs written for a non-technical executive director.

## Scope

### v1 (this spec)

- Programs: **FNS (SNAP)** and **NC Medicaid** (MAGI pathways)
- Conversational interview (Claude tool-use loop) + live editable facts panel
- Per-program results with citations, estimated FNS benefit, document checklist
- Printable action plan (print stylesheet)
- English only
- Public demo deployment with spend/rate protection; self-host via `docker run -e ANTHROPIC_API_KEY=...`

### Explicitly out of scope for v1

- Spanish output (v1.1 — mostly prompt + UI strings)
- Additional programs (WIC, LIEAP, child care subsidy — follow-up PRs; architecture must make these additive)
- Client-facing (self-service) mode — staff-facing only until the engine has mileage
- Any persistence, case records, accounts, or auth
- Intake/CRM export
- RAG over policy manuals

## Architecture

Single repository, single Docker container. Four components:

```
nc-benefits-navigator/
├── rules/        # pure Python package — the trust core
├── interview/    # LLM layer (Anthropic SDK, tool-use loop)
├── server/       # FastAPI — sessions, SSE chat, static file serving
├── web/          # React + Vite frontend
└── docs/         # adoption + rules documentation
```

### `rules/` — deterministic rules engine (pure Python)

No LLM dependency; auditable and testable in isolation. Managed with `uv`.

- **`models.py`** — Pydantic `Household` model:
  - `members[]`: age, relationship to head, pregnancy, disability, immigration category
  - `income[]`: type (earned/unearned subtypes), amount, frequency
  - `expenses[]`: shelter, utilities, dependent care, child support paid, elderly/disabled medical
  - `resources[]`: only where a program needs them
  - **Every field is `Optional`.** The engine computes with what it has and reports `missing_fields`. Partial data is the normal case, not an error.
- **`programs/fns.py`, `programs/medicaid.py`** — each exposes:
  ```python
  def evaluate(household: Household) -> ProgramResult
  ```
  `ProgramResult`: status (`likely_eligible` / `likely_ineligible` / `needs_more_info`), reasons (each with a citation), estimated benefit (FNS allotment), required documents, missing fields. Adding a program later = adding one module conforming to this interface.
- **`tables/`** — versioned YAML data files with effective dates: FPL figures, FNS gross/net income limits, max allotments, standard deductions, MAGI thresholds. **Data separate from logic** so the annual update is a data-file PR, not a code change.
- **`citations.py`** — registry mapping rule IDs → NC DHHS manual section name + URL. Every reason in every result links to its source.

### `interview/` — LLM layer

- Claude (default `claude-sonnet-4-6`, configurable via env) runs a tool-use loop with tools:
  - `update_household(patch)` — record extracted facts
  - `get_screening_status()` — current engine results + missing fields
- After every turn the server applies the patch, re-runs the engine, and returns current results + missing fields, so Claude always asks the next most useful question.
- System prompt makes the division of labor explicit: extract facts, never compute or assert eligibility; the engine's output is the only source of truth for results.

### `server/` — FastAPI

- Endpoints:
  - `POST /api/session` — create in-memory session (TTL eviction)
  - `POST /api/session/{id}/message` — chat turn, SSE streaming
  - `PATCH /api/session/{id}/household` — manual corrections from the facts panel (bypasses Claude, re-runs engine)
  - `GET /api/session/{id}/report` — printable action plan data
  - `DELETE /api/session/{id}`
- No database. Sessions die on TTL or delete.
- Demo-mode env vars: per-session message cap, global daily spend budget, rate limiting — so the public URL is safe to share.
- Serves the built `web/` assets statically.

### `web/` — React + Vite

- Two-pane layout: **chat** (left) and live **editable "Household facts" panel** (right). Staff can correct any extracted fact; edits go straight to the engine via PATCH.
- Results area: per-program cards (status, reasons with citation links), document checklist, estimated FNS benefit.
- Printable action plan via print stylesheet — staff hands paper to the client.
- Persistent disclaimer: *screening estimate, not a determination — apply at ePASS* (linked).

## Data flow

```
staff message → Claude → update_household(patch)
            → engine evaluates → results + missing_fields
            → Claude asks next question / walks through results
```

The facts panel always renders the **engine's** current state, never Claude's paraphrase. Human corrections flow straight to the engine.

## Error handling

- **Extraction mistakes are expected.** The editable facts panel is the mitigation — human-in-the-loop by design.
- **Engine never raises on partial data** — returns `needs_more_info` with `missing_fields`.
- **Anthropic API failure:** chat degrades gracefully; facts panel + engine still work, so a screening can be finished by manual field editing.
- **Invalid patches** (negative income, age 400) rejected by Pydantic validation with messages Claude can recover from in-loop.

## Testing

- **Rules engine (the serious part):**
  - pytest unit tests per rule, using the policy manuals' own worked examples as cases
  - Hypothesis property tests — e.g., raising income never flips `likely_ineligible` → `likely_eligible` all else equal
  - Golden fixtures: ~15 named realistic households with hand-verified expected outcomes for both programs
- **Interview layer:** unit tests for tool schemas and patch application; small scripted-conversation eval suite (smoke check, not CI-blocking).
- **E2E:** one Playwright happy path against a mocked LLM.

## Documentation (first-class deliverable)

- **README** — 90-second pitch, screenshot, live demo URL, `docker run` one-liner.
- **`docs/adopting.md`** — for an ED with no IT staff: what it does, what it costs (~$20/mo), step-by-step setup with screenshots.
- **`docs/rules.md`** — every rule mapped to its manual section; how to update annual figures.
- **`docs/contributing.md`** — including how to add a program module.
- License: **MIT**.

## Deployment

- Public demo: single container on Fly.io/Railway, Keegan's API key, demo-mode caps enabled.
- Self-host: `docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... <image>` — that line, in the README, is the whole install.

## Success criteria

1. A non-technical caseworker can complete a realistic screening (chat → corrected facts → printed action plan) in under 10 minutes without training.
2. Every eligibility reason in the output links to a real NC DHHS manual section.
3. Golden-fixture households produce hand-verified correct results for both programs.
4. A stranger can self-host from the README alone.
5. The public demo URL survives being shared (spend caps hold).
