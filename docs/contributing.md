# Contributing

## Dev setup

Requirements: [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
git clone https://github.com/keeganburkart/nc-benefits-navigator.git
cd nc-benefits-navigator
uv sync --all-extras         # Python deps (incl. dev)
cd web && npm install        # UI deps
```

Run it locally:

```bash
# API + engine (serves web/dist if built):
ANTHROPIC_API_KEY=sk-... uv run uvicorn server.app:app --port 8000

# UI with hot reload (proxies /api to :8000):
cd web && npm run dev
```

No key? Set `NAV_FAKE_LLM=1` instead of a key and the chat replays a canned
deterministic conversation — good enough to develop everything except prompt
behavior.

## Tests

```bash
uv run pytest                # 300+ engine/interview/server tests (fast, offline)
uv run pytest -m eval -s     # 10 real-API interview evals, 5 scenarios (needs ANTHROPIC_API_KEY, ~$0.40)
uv run pytest -m adversarial -s  # 11 real-API adversarial evals, 8 probes (needs ANTHROPIC_API_KEY, ~$0.30)
cd web && npm test           # UI component tests (Vitest)
cd web && npm run e2e        # Playwright E2E — real server + fake LLM (build web first)
uv run ruff check .          # lint
```

The eval suite is excluded from the default run on purpose: it costs real
money and its assertions are behavioral, not exact-match. Run it whenever you
touch `interview/prompt.py` or `interview/loop.py`. Scenarios live in
`tests/interview/test_evals.py` on the `run_scenario` harness
(`tests/interview/eval_harness.py`): a happy path, an over-income household,
a 65+ ABD hand-off, an adversarial verdict/SSN probe, and a mid-conversation
fact correction. Adding one is a fixture (the script) plus a test (the
behavioral assertions).

The adversarial suite (`tests/interview/test_adversarial_evals.py`) probes the
failure modes that matter most here: inventing unstated facts, summarizing
without probing expenses, prompt injection, pressure to falsify income, invalid
values, and PII dumps. Known-open bugs are xfail-marked with their task number
and flip to hard assertions when fixed. Its offline sibling
(`tests/rules/test_adversarial.py`) pins engine edge cases beyond the property
tests' bounds — oversized households, exact limit boundaries, degenerate income —
and runs in the default suite for free.

**Architecture invariant (enforced by review):** `rules/` imports nothing from
`interview/`, `server/`, or the `anthropic` package. `interview/` may import
`rules/`. The LLM never decides eligibility — it can only call
`update_household` and read back what the deterministic engine returned. Keep
it that way.

## Adding a program

Programs are pluggable. Each one is a single pure function.

1. Create `rules/programs/yourprogram.py` exposing
   `evaluate(household: Household) -> ProgramResult` (see
   `rules/programs/types.py` for the result contract: status, cited reasons,
   documents, missing fields). Model it on `fns.py` — decompose into phase
   helpers, all money in integer cents, `Decimal` + `ROUND_HALF_UP` only.
   A program may consult other programs' results (see `wic.py`/`lifeline.py`
   adjunctive checks — they call `fns.evaluate`/`medicaid.evaluate` directly);
   that stays pure and deterministic, but word such reasons as contingent on
   actual approval, since a screen is not enrollment.
2. Put every annual figure in a new `rules/tables/yourprogram.yaml` with
   `source_url`, `effective_from`/`effective_to` — never hardcode numbers.
3. Register every rule you apply in `rules/citations.py` (each reason must
   carry a real manual citation) and add your rule→table rows to
   `scripts/gen_rules_doc.py`, then regenerate `docs/rules.md`.
4. Register the program in `PROGRAMS` (`rules/programs/__init__.py`) and add
   it to `_PROGRAM_ORDER` in `rules/engine.py` — a module-level assert fails
   if the two drift.
5. Add hand-computed golden fixtures in `tests/fixtures/golden/` (marked
   `verified: false` until a second person checks them) plus unit tests.
   The interview layer and UI pick the new program up automatically.

## Conduct & PR expectations

Be kind; assume good faith; no harassment — standard
[Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/)
rules apply.

For PRs: keep them focused; all tests green; new behavior comes with tests;
benefit figures and citations must link to their primary source so a reviewer
can verify them. **Correctness beats cleverness everywhere in `rules/`** —
these numbers end up in front of families making food-budget decisions.
