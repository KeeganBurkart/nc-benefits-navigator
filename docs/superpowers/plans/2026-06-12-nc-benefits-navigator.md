# NC Benefits Navigator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Staff-facing AI benefits screener for NC nonprofits — conversational interview + deterministic FNS/Medicaid rules engine + printable cited action plan, shipped as one Docker container.

**Mode:** Contract — tasks specify behavior contracts, interfaces, and invariants; the executing agent owns implementation design. Do not expect code blocks; exact strings/schemas given here ARE contracts and must match verbatim.

**Architecture:** Pure-Python rules engine (`rules/`) that computes eligibility deterministically from a partially-filled Pydantic `Household`; an LLM interview layer (`interview/`) that only extracts facts via tool calls; a FastAPI server (`server/`) with in-memory sessions and SSE chat; a React/Vite two-pane UI (`web/`) served statically by the server. The LLM never decides eligibility. Nothing is persisted.

**Tech Stack:** Python 3.12 + uv, Pydantic v2, FastAPI, Anthropic Python SDK, pytest + Hypothesis, React 18 + Vite + TypeScript, Playwright, Docker.

**Spec:** `docs/superpowers/specs/2026-06-12-nc-benefits-navigator-design.md` — read it before starting any task.

**Global invariants (every task must preserve):**
1. `rules/` imports nothing from `interview/`, `server/`, or the `anthropic` package — ever.
2. Every field on every household model is `Optional`; `evaluate()` never raises on partial data — it returns `needs_more_info` with `missing_fields`.
3. Every `Reason` carries a `Citation` resolving to a real NC DHHS / USDA manual section name + URL.
4. No database, no file persistence of client data, no auth. Sessions are in-memory only.
5. All dollar amounts are `int` cents internally; monthly normalization happens at model boundary.

---

## Repository layout (Task 1 creates this)

```
nc-benefits-navigator/
├── pyproject.toml            # uv project: rules, interview, server packages + dev deps
├── rules/
│   ├── __init__.py
│   ├── models.py             # Household + patch application
│   ├── engine.py             # screen_all()
│   ├── citations.py          # citation registry
│   ├── tables/
│   │   ├── loader.py
│   │   ├── fpl.yaml
│   │   ├── fns.yaml
│   │   └── medicaid.yaml
│   └── programs/
│       ├── __init__.py       # PROGRAMS registry
│       ├── fns.py
│       └── medicaid.py
├── interview/
│   ├── __init__.py
│   ├── prompt.py             # system prompt builder
│   ├── tools.py              # tool schemas + dispatch
│   └── loop.py               # streaming agent loop
├── server/
│   ├── __init__.py
│   ├── app.py                # FastAPI app factory, static serving
│   ├── sessions.py           # in-memory store, TTL, caps
│   ├── routes.py             # API endpoints
│   └── config.py             # env var settings
├── web/                      # Vite + React + TS
│   └── src/
│       ├── App.tsx           # two-pane layout
│       ├── api.ts            # typed client + SSE
│       ├── components/
│       │   ├── Chat.tsx
│       │   ├── FactsPanel.tsx
│       │   ├── ResultsCards.tsx
│       │   └── ActionPlan.tsx
│       └── types.ts          # mirrors API JSON shapes
├── tests/
│   ├── rules/                # unit + property + golden
│   ├── interview/
│   ├── server/
│   └── fixtures/golden/      # ~15 household YAML fixtures
├── e2e/                      # Playwright
├── Dockerfile
├── fly.toml
├── README.md
├── LICENSE                   # MIT
└── docs/
    ├── adopting.md
    ├── rules.md
    └── contributing.md
```

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `rules/__init__.py`, `interview/__init__.py`, `server/__init__.py`, `tests/conftest.py`, `.gitignore`, `LICENSE`
- Create: `web/` via Vite scaffold

- [ ] **Step 1: Python workspace.** Single uv project named `nc-benefits-navigator`, Python ≥3.12. Runtime deps: `pydantic>=2`, `fastapi`, `uvicorn[standard]`, `anthropic`, `pyyaml`, `sse-starlette`. Dev deps: `pytest`, `pytest-asyncio`, `hypothesis`, `httpx`, `ruff`. Packages `rules`, `interview`, `server` are top-level importable.
- [ ] **Step 2: Verify.** `uv sync` succeeds; `uv run python -c "import rules, interview, server"` exits 0; `uv run pytest` reports "no tests ran" cleanly.
- [ ] **Step 3: Web scaffold.** `npm create vite@latest web -- --template react-ts`; strip demo content to an empty `App.tsx` rendering `<h1>NC Benefits Navigator</h1>`. `npm run build` succeeds.
- [ ] **Step 4: Housekeeping.** `.gitignore` (Python, node, dist, .env). MIT `LICENSE` (copyright Keegan Burkart). Ruff configured in `pyproject.toml` (defaults are fine).
- [ ] **Step 5: Commit** `chore: scaffold project`.

---

### Task 2: Household models + patch application

**Files:**
- Create: `rules/models.py`
- Test: `tests/rules/test_models.py`

**Contract — models (Pydantic v2, every field Optional unless noted):**
- `Member`: `id: str` (required, caller-assigned like `"m1"`), `age: int | None`, `relationship: Literal["self","spouse","child","other_relative","unrelated"] | None`, `is_pregnant: bool | None`, `is_disabled: bool | None` (receives disability-based benefit or meets program disability standard), `immigration_status: Literal["citizen","qualified_immigrant","not_qualified","unknown"] | None`, `is_student: bool | None`.
- `IncomeItem`: `member_id: str | None`, `kind: Literal["wages","self_employment","unemployment","ssi","ssdi","social_security","child_support_received","other"] | None`, `amount_cents: int | None` (≥0), `frequency: Literal["hourly","weekly","biweekly","semimonthly","monthly","yearly"] | None`, `hours_per_week: float | None` (used only when frequency is hourly).
- `Expenses`: `rent_or_mortgage_cents`, `utilities_included: bool | None`, `pays_heating_cooling: bool | None`, `dependent_care_cents`, `child_support_paid_cents`, `medical_expenses_elderly_disabled_cents` — all monthly, `int | None`.
- `Household`: `members: list[Member]` (defaults `[]`), `income: list[IncomeItem]` (defaults `[]`), `expenses: Expenses` (defaults empty), `county: str | None`, `purchases_and_prepares_together: bool | None`.
- `monthly_cents(item: IncomeItem) -> int | None` — normalization: hourly×hours×4.33, weekly×4.33, biweekly×2.17, semimonthly×2, yearly÷12; returns `None` if amount/frequency missing. Round to nearest cent, half-up.
- `apply_patch(household, patch: dict) -> Household` — deep-merge semantics: scalar fields overwrite; `members`/`income` lists are merged **by `member_id`/list-item `id`**: patch items with a matching id update that item field-wise, new ids append; a patch item `{"id": "m2", "_delete": true}` removes it. Returns a NEW validated Household (no mutation). Invalid values (negative amounts, age outside 0–125) raise `pydantic.ValidationError` whose message names the offending field.
- `missing_summary(household) -> list[str]` — dotted paths of None fields that any program might need (e.g., `"members[m1].age"`, `"income[0].frequency"`). Exact path format: `members[<id>].<field>`, `income[<index>].<field>`, `expenses.<field>`, `<field>` for top-level.

- [ ] **Step 1: Write failing tests** covering: construction from `{}` is valid; monthly normalization for each frequency (use exact expected values, e.g. $15.00/hr × 20h → $129,900 cents... compute precisely with 4.33); patch merge by id (update, append, delete); patch immutability; validation rejects negative income and age 400 with field name in message; `missing_summary` path format.
- [ ] **Step 2: Run** `uv run pytest tests/rules/test_models.py` — all fail (module missing).
- [ ] **Step 3: Implement** `rules/models.py` to the contract.
- [ ] **Step 4: Run** — all pass.
- [ ] **Step 5: Commit** `feat(rules): household models and patch application`.

---

### Task 3: Tables — versioned program data

**Files:**
- Create: `rules/tables/loader.py`, `rules/tables/fpl.yaml`, `rules/tables/fns.yaml`, `rules/tables/medicaid.yaml`
- Test: `tests/rules/test_tables.py`

**Contract — YAML schema (every table file):**
```yaml
source_url: "<authoritative URL>"
source_name: "<e.g. USDA FNS FY2026 COLA Memo>"
effective_from: "2025-10-01"
effective_to: "2026-09-30"
values: { ... }   # table-specific
```
- `fpl.yaml` values: `monthly_cents_by_household_size: {1: ..., 2: ..., ..., 8: ...}` plus `additional_member_cents` — 2026 HHS poverty guidelines, 48 contiguous states.
- `fns.yaml` values: per household size 1–10: `gross_limit_200pct_cents` (BBCE), `net_limit_100pct_cents`, `max_allotment_cents`; plus `standard_deduction_cents` by size band, `earned_income_deduction_pct: 0.20`, `excess_shelter_cap_cents`, `homeless_shelter_deduction_cents`, `standard_utility_allowance_cents` (NC SUA), `medical_deduction_threshold_cents: 3500`. FY2026 values (effective 2025-10-01).
- `medicaid.yaml` values: MAGI income limits as % of FPL per category: `adult_expansion_pct: 138` (NC expansion, live since Dec 2023), `pregnant_pct`, `child_pct_by_age_band: {"0-5": ..., "6-18": ...}`, `parent_caretaker_pct` — NC's actual percentages from NC Medicaid eligibility tables.
- `loader.py`: `load_table(name: str) -> Table` (frozen dataclass exposing `values`, `source_url`, `source_name`, `effective_from/to`); `assert_current(table, today: date)` raises `StaleTableError` naming the table and its `effective_to` when out of range. Loader caches; YAML read once.

**Data-sourcing invariant:** every figure MUST be fetched from the authoritative source (USDA FNS COLA memo for FY2026; HHS 2026 poverty guidelines; NC Medicaid income-limits page) via web lookup during implementation — do NOT supply numbers from model memory. Record the URL you used in `source_url`. ⚠️ **Human gate: Keegan hand-verifies every figure before v1 ships (spec success criterion 3).**

- [ ] **Step 1: Write failing tests**: loader returns typed table; `assert_current` passes for 2026-06-12 and raises `StaleTableError` for 2026-12-01 against an `effective_to` of 2026-09-30; all three YAML files parse and contain every key named in this contract; all cents values are positive ints; FPL size-1 monthly value is consistent with the annual guideline ÷ 12 (cross-check inside the test using the annual figure also stored in the YAML as `annual_cents_by_household_size`).
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement** loader + fetch real figures from authoritative sources and populate the three YAML files.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `feat(rules): versioned program tables with sourced FY2026 figures`.

---

### Task 4: Citations registry

**Files:**
- Create: `rules/citations.py`
- Test: `tests/rules/test_citations.py`

**Contract:**
- `Citation` frozen dataclass: `rule_id: str`, `manual: str`, `section: str`, `title: str`, `url: str`.
- `cite(rule_id: str) -> Citation` — raises `KeyError` with the rule_id if unregistered.
- Registry is a literal dict in this file. Required rule_ids (used by Tasks 5–6): `fns.gross_income`, `fns.net_income`, `fns.bbce`, `fns.elderly_disabled_exemption`, `fns.allotment`, `fns.deductions.standard`, `fns.deductions.earned_income`, `fns.deductions.shelter`, `fns.deductions.medical`, `fns.deductions.dependent_care`, `fns.deductions.child_support`, `fns.immigration`, `fns.household_composition`, `medicaid.expansion_adult`, `medicaid.pregnant`, `medicaid.child`, `medicaid.parent_caretaker`, `medicaid.magi_income`, `medicaid.immigration`, `doc.identity`, `doc.income`, `doc.residency`, `doc.immigration`, `doc.expenses`.
- URLs must point at real, currently-live pages: NC FNS manual sections (NC DHHS policy manuals site) and NC Medicaid MAGI manual sections (MA-3300 family), USDA SNAP eligibility page where NC manual lacks a stable URL. Verify each URL returns HTTP 200 during implementation (web lookup, same rule as Task 3: no URLs from memory).
- `all_citations() -> list[Citation]` for the docs generator (Task 13).

- [ ] **Step 1: Write failing tests**: `cite` returns a Citation for every required rule_id above (parametrized over the literal list); unknown id raises KeyError; every URL starts with `https://`; no duplicate rule_ids.
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement** with verified real URLs.
- [ ] **Step 4: Run** — pass.
- [ ] **Step 5: Commit** `feat(rules): citation registry mapping rules to NC DHHS manual sections`.

---

### Task 5: FNS (SNAP) program module

**Files:**
- Create: `rules/programs/__init__.py`, `rules/programs/fns.py`, shared result types in `rules/programs/types.py`
- Test: `tests/rules/test_fns.py`

**Contract — shared types (`types.py`):**
- `Status = Literal["likely_eligible","likely_ineligible","needs_more_info"]`
- `Reason`: `rule_id: str`, `text: str` (plain-language, client-readable), `citation: Citation`.
- `DocumentRequirement`: `name: str`, `why: str`, `rule_id: str`.
- `ProgramResult`: `program: Literal["fns","medicaid"]`, `program_label: str`, `status: Status`, `reasons: list[Reason]`, `estimated_benefit_cents: int | None`, `required_documents: list[DocumentRequirement]`, `missing_fields: list[str]` (same dotted-path format as Task 2).
- `rules/programs/__init__.py` exposes `PROGRAMS: dict[str, Callable[[Household], ProgramResult]]` — adding a future program = one module + one registry entry.

**Contract — FNS logic (NC FNS manual + standard SNAP math, FY2026 tables from Task 3):**
- Household unit: members with `purchases_and_prepares_together` not False. If that field is None and members > 1, it's a missing field.
- Immigration: members with `immigration_status == "not_qualified"` are excluded from the unit but their income still counts proportionally per SNAP prorating — v1 simplification contract: count their income fully and add a Reason (rule `fns.immigration`) noting the household is mixed-status and the estimate is conservative; `"unknown"`/None → missing field.
- Gross income test: sum of `monthly_cents` over countable income (exclude SSI? — no: SSI counts for SNAP; exclude child_support_received? — no, counts; loans/one-time gifts are out of scope of the model). NC applies **BBCE: gross limit = 200% FPL** (rule `fns.bbce`). Households containing an elderly (60+) or disabled member skip the gross test entirely (rule `fns.elderly_disabled_exemption`).
- Net income test: gross − deductions ≤ 100% FPL (rule `fns.net_income`). Deductions, each with its own rule_id: standard deduction (by unit size); 20% of earned income (wages + self_employment); dependent care; child support paid; medical expenses over $35/month for elderly/disabled members only; excess shelter = shelter costs (rent + SUA if `pays_heating_cooling`) minus half of income-after-other-deductions, capped at `excess_shelter_cap_cents` unless the unit has an elderly/disabled member (uncapped).
- Allotment estimate: `max_allotment − round(0.3 × net_income)`, floor 0; if eligible and unit size ≤ 2 the federal minimum-benefit floor applies (value in `fns.yaml` as `minimum_allotment_cents`).
- Status: `needs_more_info` when any input required by a test the household hasn't already failed is missing — but **fail fast**: if gross income from known items alone already exceeds the limit, return `likely_ineligible` even with missing fields. `likely_eligible` requires both tests passed with no missing required inputs.
- Required documents: always identity (`doc.identity`) + residency (`doc.residency`); income docs per income kind present (`doc.income`); expense verification when a deduction was claimed (`doc.expenses`); immigration docs when any member is `qualified_immigrant` (`doc.immigration`). Each `why` explains in one sentence what the document proves.
- Every Reason text must be understandable by the client, not the caseworker: "Your household's monthly income before deductions ($2,430) is under the limit for a household of 3 ($4,304)" — actual numbers interpolated, no jargon, no rule ids in text.

- [ ] **Step 1: Write failing tests** — unit tests per rule using worked examples you construct by hand from the FY2026 tables (show arithmetic in test comments): gross pass/fail at the boundary (exactly at limit = pass); elderly/disabled gross-test skip; each deduction changes net income by the documented amount; shelter cap applied/uncapped; allotment formula incl. minimum benefit; fail-fast ineligibility with missing fields present; mixed-status reason emitted; document list contents per scenario; every reason's citation resolves via `cite()`.
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement** `types.py` + `fns.py` + registry.
- [ ] **Step 4: Run** — pass. Also run full suite.
- [ ] **Step 5: Commit** `feat(rules): FNS screening with FY2026 NC BBCE rules`.

---

### Task 6: Medicaid program module

**Files:**
- Create: `rules/programs/medicaid.py`
- Modify: `rules/programs/__init__.py` (register)
- Test: `tests/rules/test_medicaid.py`

**Contract — MAGI screening (NC, post-expansion):**
- Evaluate each member against categories in priority order; household result is `likely_eligible` if ANY member qualifies, and `reasons` lists per-member findings (text names the member by id-free description: "the 7-year-old child", "the pregnant adult").
- Categories (limits from `medicaid.yaml` × FPL table, household size = MAGI household = v1 simplification: all members; note this in a Reason when relationships suggest tax-household differences, rule `medicaid.magi_income`):
  - Child (age ≤ 18): income ≤ child band limit for age.
  - Pregnant member: ≤ pregnant limit.
  - Parent/caretaker of a child ≤ 18 in household: ≤ parent_caretaker limit.
  - Expansion adult (19–64, not otherwise eligible): ≤ 138% FPL (rule `medicaid.expansion_adult`).
  - Age ≥ 65 → out of MAGI scope: Reason text says aged/blind/disabled Medicaid uses different rules this tool doesn't screen, status contribution `needs_more_info`.
- Countable MAGI income: wages, self_employment, unemployment, social_security/ssdi count; **SSI and child_support_received do NOT count** (contrast with FNS — this asymmetry must be tested).
- Immigration: `not_qualified` member → that member gets a Reason (rule `medicaid.immigration`) pointing out emergency-services-only coverage; doesn't block other members.
- Missing age/income data → `needs_more_info` with missing fields; same fail-fast principle as FNS.
- Documents: identity, residency, income, immigration (same doc rule_ids as Task 5).

- [ ] **Step 1: Write failing tests** — per-category boundary cases with hand-computed FY/CY-correct numbers in comments; SSI counts for FNS but not Medicaid (cross-program test); 65+ produces the ABD hand-off reason; mixed-status handling; any-member-eligible household status; missing-data behavior.
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full suite — pass.
- [ ] **Step 5: Commit** `feat(rules): NC Medicaid MAGI screening`.

---

### Task 7: Engine façade, property tests, golden fixtures

**Files:**
- Create: `rules/engine.py`, `tests/rules/test_properties.py`, `tests/rules/test_golden.py`, `tests/fixtures/golden/*.yaml` (~15 files)
- Test: above

**Contract — `engine.py`:**
- `screen_all(household) -> ScreeningResult` where `ScreeningResult`: `programs: list[ProgramResult]` (stable order: fns, medicaid), `household: Household` (echo), `missing_fields: list[str]` (union, deduped, stable order), `generated_disclaimer: str` — exact string: `"This is a screening estimate, not an eligibility determination. Only your county DSS can determine eligibility. Apply online at https://epass.nc.gov."`
- `ScreeningResult.model_dump_json()`-compatible (Pydantic) — this exact JSON shape is the API/UI contract.

**Contract — property tests (Hypothesis, against `screen_all`):**
1. Never raises, for ANY household the strategy can generate (including empty, partial, adversarial values within validation bounds).
2. Income monotonicity: adding an income item to a `likely_ineligible`-for-income household never makes it `likely_eligible` (per program).
3. Deduction monotonicity (FNS): increasing a deductible expense never decreases the estimated allotment.
4. Idempotence: `screen_all(h)` twice → identical results (no hidden state).
5. Every reason's `citation.url` non-empty; statuses always within the Literal.

**Contract — golden fixtures:** ~15 YAML files, each: `name`, `description` (one realistic sentence, e.g. "Single mother of two, part-time retail, pays market rent in Wilmington"), `household: {...}`, `expected: {fns: {status, estimated_benefit_cents}, medicaid: {status}}`. Cover: clearly eligible both; clearly ineligible both; FNS-only; Medicaid-only (income between 138% and 200% FPL); elderly/disabled deduction paths; mixed-status; pregnant member; 65+ ABD hand-off; empty household; partial data → needs_more_info. ⚠️ **Human gate: expected values are hand-verified by Keegan against the manuals before v1 ships — mark each fixture `verified: false` until he flips it; the golden test asserts outcomes regardless, the flag tracks human review.**

- [ ] **Step 1: Write `engine.py` test + failing golden/property tests** (strategies generate via the patch API to stay within validation bounds).
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement** `engine.py`; author the 15 fixtures with hand-computed expectations (arithmetic in YAML comments).
- [ ] **Step 4: Run** full suite incl. Hypothesis — pass, no flaky examples (fix engine, never the property, on failure).
- [ ] **Step 5: Commit** `feat(rules): engine façade, property tests, golden household fixtures`.

---

### Task 8: Interview layer — prompt, tools, agent loop

**Files:**
- Create: `interview/prompt.py`, `interview/tools.py`, `interview/loop.py`
- Test: `tests/interview/test_tools.py`, `tests/interview/test_loop.py`

**Contract — `tools.py`:**
- Two Anthropic tool schemas:
  - `update_household`: input `{"patch": <object>}` — description tells the model the patch semantics from Task 2 (merge by id, `_delete`) and that amounts are **dollars in the patch** (e.g. `"amount": 1250.50`) — the dispatcher converts to cents. This is the one place dollars appear.
  - `get_screening_status`: no input.
- `dispatch(session, tool_name, tool_input) -> str` — applies patch via `apply_patch` (converting dollar floats to int cents), re-runs `screen_all`, stores both on the session, and returns a JSON string: `{"household": ..., "screening": {per-program status + missing_fields + one-line summaries}}`. On `ValidationError`, returns `{"error": "<field>: <message>"}` (loop continues — the model corrects itself).
- `interview/` imports `rules/` but `rules/` never imports `interview/` (global invariant 1).

**Contract — `prompt.py`:** `build_system_prompt(screening_summary: str) -> str`. Required behaviors the prompt must encode (test by string presence of key directives, full behavior tested in Task 12 evals):
- You assist a **caseworker** sitting with a client; address the caseworker.
- Extract facts into `update_household` as soon as stated; never re-ask recorded facts.
- **Never state or imply an eligibility conclusion yourself** — only relay what the screening tool returned, with its numbers.
- Ask ONE question per turn, the most useful one given `missing_fields`; plain 8th-grade language; never request SSN or immigration documents in chat — that's for the document checklist.
- When both programs leave `needs_more_info` empty, stop interviewing and summarize results, reminding that the printable plan has details, and always include the disclaimer sentence (exact string from Task 7).

**Contract — `loop.py`:**
- `async run_turn(session, user_message) -> AsyncIterator[Event]` where `Event` is a tagged union (Pydantic): `{"type":"text","delta":str}` | `{"type":"household","data":<Household JSON>}` | `{"type":"screening","data":<ScreeningResult JSON>}` | `{"type":"done"}` | `{"type":"error","message":str}`.
- Uses Anthropic streaming with tool use; loops until end_turn; emits `household` + `screening` events immediately after each successful `update_household` dispatch.
- Model from config (Task 10), default `claude-sonnet-4-6`, `max_tokens` 2048.
- Anthropic API errors → single `error` event with a human message ("The AI assistant is unreachable — you can keep editing the household facts directly."), never a stack trace; session stays usable.
- Conversation history kept on the session object, capped at 50 messages (oldest user/assistant pairs dropped, system prompt rebuilt each turn with current screening summary).

- [ ] **Step 1: Write failing tests** — tools: dollar→cent conversion; patch dispatch updates session + returns JSON with both keys; ValidationError → error JSON, session unchanged. Loop: with a **mocked Anthropic client** (scripted: text → tool_use → text → end_turn), events arrive in contract order; API-error path emits single error event. Prompt: directives present.
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full suite — pass.
- [ ] **Step 5: Commit** `feat(interview): tool-use agent loop with fact extraction`.

---

### Task 9: Server — sessions, API, SSE

**Files:**
- Create: `server/config.py`, `server/sessions.py`, `server/routes.py`, `server/app.py`
- Test: `tests/server/test_sessions.py`, `tests/server/test_api.py`

**Contract — `config.py`** (Pydantic Settings, env prefix `NAV_`):
- `anthropic_api_key: str` (also accepts bare `ANTHROPIC_API_KEY`), `model: str = "claude-sonnet-4-6"`, `session_ttl_minutes: int = 60`, `max_messages_per_session: int = 40`, `daily_budget_usd: float = 10.0`, `demo_mode: bool = False`, `port: int = 8000`.

**Contract — `sessions.py`:**
- `Session`: `id` (uuid4 hex), `household`, `screening`, `messages` (anthropic-format history), `created_at`, `last_active`, `message_count`.
- In-memory dict store; TTL eviction sweep on access (no background thread needed); `create/get/delete`; `get` on expired/missing → `KeyError`.
- Budget guard: module-level day-keyed token counter; `charge(input_tokens, output_tokens)` estimates USD at the configured model's public pricing (put the two $/MTok numbers in `config.py` as `price_in`/`price_out` so they're updatable); when day total exceeds `daily_budget_usd`, raises `BudgetExceeded`.

**Contract — `routes.py`** (all JSON; errors as `{"error": str}` with proper status):
- `POST /api/session` → 201 `{"session_id": str, "screening": <empty-household ScreeningResult>}`.
- `POST /api/session/{id}/message` body `{"message": str}` → SSE stream of Task-8 events (`sse-starlette`, event name = event type, data = JSON). 404 unknown session; 429 with `{"error":"message limit reached"}` at message cap; 429 `{"error":"daily demo budget exhausted"}` on BudgetExceeded; message length cap 2000 chars → 422.
- `PATCH /api/session/{id}/household` body `{"patch": {...}}` (dollar semantics, same converter as tools) → 200 `{"household":..., "screening":...}`; 422 with field name on validation error. **Does not touch the LLM.**
- `GET /api/session/{id}/report` → 200 `{"household":..., "screening":..., "generated_at": iso8601}`.
- `DELETE /api/session/{id}` → 204.
- `GET /healthz` → `{"ok": true}`.

**Contract — `app.py`:** app factory; serves `web/dist` at `/` with SPA fallback to `index.html` for non-`/api` paths; CORS not needed (same origin); when `demo_mode` is true, responses include header `X-Demo-Mode: 1` and the UI shows the demo banner (Task 11).

- [ ] **Step 1: Write failing tests** (httpx ASGI client, interview loop mocked): session lifecycle incl. TTL expiry (freeze time via injected clock — design `sessions.py` to take a `now` callable); every route contract above incl. all error codes; PATCH runs engine without LLM; budget guard trips at threshold.
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** full suite — pass. Manual smoke: `uv run uvicorn server.app:create_app --factory` starts; `curl localhost:8000/healthz` ok.
- [ ] **Step 5: Commit** `feat(server): in-memory sessions, SSE chat, demo caps`.

---

### Task 10: Web UI — layout, chat, facts panel

**Files:**
- Create: `web/src/types.ts`, `web/src/api.ts`, `web/src/App.tsx`, `web/src/components/Chat.tsx`, `web/src/components/FactsPanel.tsx`
- Test: `web/src/__tests__/` (Vitest + Testing Library — add dev deps)

**Contract:**
- `types.ts` mirrors the JSON shapes of `Household`, `ScreeningResult`, SSE events — field names identical to the Python `model_dump()` output (snake_case; do not camelize).
- `api.ts`: typed fetch wrappers for all Task-9 endpoints + `streamMessage(sessionId, text, onEvent)` consuming SSE.
- `App.tsx`: creates a session on load; two-pane responsive layout — Chat left (~60%), FactsPanel + results right; on `household`/`screening` SSE events updates the right pane live; "New screening" button = DELETE + fresh session with confirm dialog ("This will erase everything — nothing is saved.").
- `Chat.tsx`: message list with streaming text, input box (disabled while streaming), error events render as an inline system notice (not a toast), retry button re-sends last message.
- `FactsPanel.tsx`: renders the engine's household — members table (age, relationship, flags), income table (kind, amount as dollars, frequency), expenses list. **Every cell editable in place**; edits debounce 500ms → PATCH → panel re-renders from server response (server state is truth, never local optimistic state). Add/remove member and income rows. Validation errors from PATCH render inline at the offending field.
- Persistent footer disclaimer, exact Task-7 string, with `epass.nc.gov` as a live link. Demo banner when `X-Demo-Mode` header was present on session create: "Public demo — example data only. Do not enter real client information."
- Styling: plain hand-written CSS (one stylesheet, CSS variables), clean and uncluttered; no component library, no Tailwind (keeps the repo approachable). Must be readable at 1280×800 and stack vertically below 900px.

- [ ] **Step 1: Write failing component tests**: FactsPanel renders household JSON and fires PATCH with dollar semantics on edit; Chat renders streamed deltas in order; error event → notice + retry; App wires session create.
- [ ] **Step 2: Run** `npm test` — fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `npm test` + `npm run build` — pass. Manual smoke against running server with real API key: complete one conversation, edit a fact, watch results change.
- [ ] **Step 5: Commit** `feat(web): chat + live editable facts panel`.

---

### Task 11: Web UI — results, document checklist, printable plan

**Files:**
- Create: `web/src/components/ResultsCards.tsx`, `web/src/components/ActionPlan.tsx`, print stylesheet
- Modify: `web/src/App.tsx`
- Test: extend `web/src/__tests__/`

**Contract:**
- `ResultsCards.tsx`: one card per program — program_label, status pill (green `likely_eligible` "Likely eligible", red `likely_ineligible` "Likely not eligible", amber `needs_more_info` "More info needed"); FNS card shows `estimated_benefit_cents` as "$X/month estimated" when present; each reason rendered with its citation as a superscript link (`title` = manual section name, href = url); missing fields listed as plain questions ("What is the rent payment?") — map dotted paths to human phrasing with a lookup table, fall back to the raw path.
- `ActionPlan.tsx` + "Print action plan" button: print-only view (CSS `@media print` hides app chrome) containing: date, per-program status + reasons with footnoted citations (numbered, URLs printed in a footnote list), document checklist grouped with checkboxes (name + why), "How to apply" block (ePass URL + "or visit your county DSS office"), disclaimer string, and a footer "Generated by NC Benefits Navigator (open source) — not affiliated with NC DHHS." Nothing about the conversation itself appears (no chat transcript).
- Document checklist deduplicates across programs by document name, listing which program(s) need it.

- [ ] **Step 1: Write failing tests**: status pill mapping; benefit formatting ($ from cents); citation links; checklist dedup across programs; print view contains disclaimer + apply block and no chat content.
- [ ] **Step 2: Run** — fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** tests + build; manual print-preview check in browser.
- [ ] **Step 5: Commit** `feat(web): results cards and printable action plan`.

---

### Task 12: Interview eval suite + E2E

**Files:**
- Create: `tests/interview/test_evals.py` (marked `@pytest.mark.eval`, excluded from default run via marker config), `e2e/screening.spec.ts`, Playwright config

**Contract — evals (real API, run manually: `uv run pytest -m eval`):**
- 5 scripted conversations (caseworker utterances as fixtures) asserting tool-call behavior, not exact wording: (1) stated facts produce a patch within the next model turn; (2) model never re-asks a recorded fact across the script; (3) model text after a screening event contains no eligibility verdict that contradicts engine status, and contains the engine's numbers when summarizing; (4) one-question-per-turn (count `?` heuristically, allow ≤2); (5) full happy path reaches a both-programs-resolved summary containing the disclaimer string.
- Each eval prints token cost; suite total must stay under $1.

**Contract — Playwright E2E (mocked LLM):**
- Server started with `NAV_FAKE_LLM=1` — add this to config: when set, `loop.py` substitutes a deterministic fake client replaying a canned tool-using conversation (lives in `interview/fake.py`, ~3 turns ending in a resolved screening). This flag is test infrastructure, documented as such.
- One spec: load app → send 3 messages → facts panel populates → edit an income amount → results update → click Print → assert action-plan view contains disclaimer and a document checklist item.

- [ ] **Step 1: Write the fake client + failing E2E spec; write eval suite.**
- [ ] **Step 2: Run** Playwright — fail before wiring, pass after. Run `pytest -m eval` once with real key; fix prompt (Task 8) if any eval fails; re-run until green.
- [ ] **Step 3: Run** full default suite — confirm evals are excluded and everything passes.
- [ ] **Step 4: Commit** `test: interview evals and Playwright E2E with fake LLM`.

---

### Task 13: Dockerfile + deployment

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `fly.toml`

**Contract:**
- Multi-stage: stage 1 `node:22-slim` builds `web/dist`; stage 2 `python:3.12-slim` + uv installs the project (no dev deps), copies `web/dist`, runs `uvicorn` via non-root user, `EXPOSE 8000`, `HEALTHCHECK` hitting `/healthz`.
- The README one-liner MUST work exactly as documented: `docker run -p 8000:8000 -e ANTHROPIC_API_KEY=sk-... ghcr.io/keeganburkart/nc-benefits-navigator` (image name final).
- `fly.toml`: demo app config — `NAV_DEMO_MODE=true`, budget/caps from env, 1 shared-cpu machine, auto-stop enabled. Secrets (API key) set via `fly secrets`, never in the file.
- Image build must not contain: tests, e2e, docs/superpowers, .git (via `.dockerignore`).

- [ ] **Step 1: Write Dockerfile + .dockerignore + fly.toml.**
- [ ] **Step 2: Verify**: `docker build .` succeeds; `docker run` with a real key serves the app at `localhost:8000`; full screening works in browser against the container; `docker run` WITHOUT a key exits with a clear one-line error naming the missing variable.
- [ ] **Step 3: Commit** `feat: single-container Docker build and Fly demo config`.
- [ ] **Step 4 (with Keegan, not automatable):** create Fly app, set secret, deploy, confirm demo URL live, confirm spend caps by exhausting a session.

---

### Task 14: Documentation

**Files:**
- Create: `README.md`, `docs/adopting.md`, `docs/rules.md`, `docs/contributing.md`

**Contract:**
- `README.md`, in order: one-paragraph pitch (what it does for whom, the LLM-never-decides-eligibility line, nothing-is-stored line); screenshot (placeholder path `docs/img/screenshot.png` — ⚠️ human gate: Keegan captures it from the live demo); demo URL; the docker one-liner; "What it screens" (FNS, Medicaid, with manual links); honest limitations list (screener-not-determination, v1 simplifications from Tasks 5–6 named explicitly: mixed-status income counting, MAGI household simplification, no ABD Medicaid); links to the three docs; license.
- `docs/adopting.md` — audience: an executive director with no IT staff. Must cover: what you need (an Anthropic API key — with step-by-step signup instructions and screenshots placeholder; a place to run Docker — recommend one specific path with exact clicks: Fly.io free tier OR a $6 DigitalOcean droplet, pick ONE and write it fully); monthly cost expectation (~$5–25 depending on volume, with the math); privacy explanation in plain English (nothing stored, what goes to Anthropic, link to Anthropic's commercial data policy); how to update annual figures (point to rules.md).
- `docs/rules.md` — generated table (write a small script `scripts/gen_rules_doc.py` using `all_citations()` + table metadata) listing every rule_id, its plain description, manual section, URL, and which table file feeds it; prose section: "Updating the annual numbers" — exact steps to PR new FPL/COLA values incl. changing `effective_from/to` and re-running golden tests.
- `docs/contributing.md`: dev setup (uv + npm commands, test commands incl. eval marker and fake-LLM flag); "Adding a program" walkthrough referencing the `PROGRAMS` registry and `ProgramResult` contract; conduct + PR expectations (short).
- All docs: no placeholder text except the two flagged image paths; every claim about behavior must be true of the code as built (verify while writing).

- [ ] **Step 1: Write `scripts/gen_rules_doc.py` + the four documents.**
- [ ] **Step 2: Verify**: a fresh clone following contributing.md reaches green tests; rules.md regenerates idempotently; README one-liner matches Dockerfile reality; adopting.md walkthrough contains no step that assumes technical knowledge it didn't teach.
- [ ] **Step 3: Commit** `docs: README, adoption guide, rules reference, contributing`.

---

## Human gates (Keegan, before calling v1 done)

1. Verify every figure in `rules/tables/*.yaml` against the cited sources (Task 3).
2. Hand-verify all golden fixtures; flip `verified: true` (Task 7).
3. Spot-check citation URLs land on the right manual sections (Task 4).
4. Run one real screening end-to-end as a caseworker would; check the printed plan reads right (Task 11).
5. Deploy demo + capture README screenshot (Tasks 13–14).
6. Success criteria check against the spec, all five.

## Task ordering & parallelism

Sequential spine: 1 → 2 → 3/4 (parallel) → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14. Tasks 3 and 4 touch disjoint files and may run in parallel; everything else depends on its predecessor's types or running services.
