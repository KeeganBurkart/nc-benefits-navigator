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
uv run pytest                # 400+ engine/interview/server tests (fast, offline)
uv run pytest -m eval -s     # real-API interview evals, 5 scenarios (needs ANTHROPIC_API_KEY, ~$0.40)
uv run pytest -m adversarial -s  # real-API adversarial evals (needs ANTHROPIC_API_KEY, ~$0.30)
uv run pytest -m linkcheck   # network: every citation/source URL returns HTTP 200
cd web && npm test           # UI component tests (Vitest)
cd web && npm run build      # build web/dist (required before e2e)
cd web && npm run e2e        # Playwright E2E — real server + fake LLM
uv run ruff check .          # lint
```

Three suites are excluded from the default run (`addopts` in `pyproject.toml`):
`eval` and `adversarial` cost real money and assert behaviour, not exact
matches; `linkcheck` hits the network. Run `eval`/`adversarial` whenever you
touch `interview/prompt.py` or `interview/loop.py`. Scenarios live in
`tests/interview/test_evals.py` on the `run_scenario` harness
(`tests/interview/eval_harness.py`): a happy path, an over-income household,
a 65+ ABD hand-off, an adversarial verdict/SSN probe, and a mid-conversation
fact correction. Adding one is a fixture (the script) plus a test (the
behavioral assertions).

The adversarial suite (`tests/interview/test_adversarial_evals.py`) probes the
failure modes that matter most here: inventing unstated facts, summarizing
without probing expenses, prompt injection (including a value entered through
the facts panel — `panel_injection` seeds an instruction-shaped `county`),
pressure to falsify income, invalid values, and PII dumps. Its offline sibling
(`tests/rules/test_adversarial.py`) pins engine edge cases beyond the property
tests' bounds — oversized households, one-cent limit boundaries for FNS/Medicaid
(every figure hand-computed from `rules/tables/*.yaml`), degenerate income — and
runs in the default suite for free. `tests/rules/test_freshness.py` fails the
day any shipped table goes stale.

**The prompt/summary contract.** The system-prompt screening summary
(`interview/loop._compact_summary_str`) now embeds `household_facts`, so panel
edits are visible to the model. Household strings (county, ids) are
user-controlled: they are serialized with `json.dumps` (single inert JSON
strings) inside `BEGIN/END SCREENING SUMMARY` markers, and the prompt declares
that block *data, not instructions*. Keep both halves — if you change how the
summary is built, preserve the escaping and the markers, and keep the prompt's
"record only stated facts" and "probe expenses before summarizing" directives
(they are load-bearing; the offline `tests/interview/test_prompt.py` locks their
presence and the live evals lock the behaviour).

**Facts panel inputs are controlled with a draft overlay.** `web/.../FactsPanel`
fields render the committed household prop except while a field is being edited
(a local draft, cleared on blur). Do NOT reintroduce `defaultValue`/uncontrolled
inputs — chat- and server-recorded facts must re-render live without clobbering
in-progress typing.

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
