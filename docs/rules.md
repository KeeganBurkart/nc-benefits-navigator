# Rules reference

<!-- GENERATED FILE — do not edit. Regenerate with:
     uv run python scripts/gen_rules_doc.py -->

Every eligibility reason the engine produces carries one of the rule ids
below, and every rule id maps to a specific section of the governing policy
manual. The engine never invents a rule: if it isn't in this table, the
screener doesn't apply it.

| Rule id | What it checks | Manual section | Fed by table |
|---|---|---|---|
| `doc.expenses` | Deductions (verification of deductible expenses) | [NC FNS Manual FNS 340](https://policies.ncdhhs.gov/document/fns-340-deductions/) | — |
| `doc.identity` | Identity (verification of applicant identity) | [NC FNS Manual FNS 205](https://policies.ncdhhs.gov/document/fns-205-identity/) | — |
| `doc.immigration` | Non-Citizen Requirements (verification of immigration status) | [NC FNS Manual FNS 227](https://policies.ncdhhs.gov/document/fns-227-non-citizen-requirements/) | — |
| `doc.income` | Whose Income Is Counted (income verification) | [NC FNS Manual FNS 350](https://policies.ncdhhs.gov/document/fns-350-whose-income-is-counted/) | — |
| `doc.residency` | Residence (verification of NC residency) | [NC FNS Manual FNS 215](https://policies.ncdhhs.gov/document/fns-215-residence/) | — |
| `fns.allotment` | Determining Benefit Levels (allotment / Thrifty Food Plan) | [NC FNS Manual FNS 360](https://policies.ncdhhs.gov/document/fns-360-determining-benefit-levels/) | rules/tables/fns.yaml |
| `fns.bbce` | Categorical Eligibility (broad-based categorical eligibility, 200% gross income limit) | [NC FNS Manual FNS 220](https://policies.ncdhhs.gov/document/fns-220-categorical-eligibility/) | rules/tables/fns.yaml |
| `fns.deductions.child_support` | Deductions (legally obligated child support deduction) | [NC FNS Manual FNS 340](https://policies.ncdhhs.gov/document/fns-340-deductions/) | — |
| `fns.deductions.dependent_care` | Deductions (dependent care deduction) | [NC FNS Manual FNS 340](https://policies.ncdhhs.gov/document/fns-340-deductions/) | — |
| `fns.deductions.earned_income` | Deductions (earned income deduction) | [NC FNS Manual FNS 340](https://policies.ncdhhs.gov/document/fns-340-deductions/) | rules/tables/fns.yaml |
| `fns.deductions.homeless_shelter` | Deductions (homeless shelter deduction) | [NC FNS Manual FNS 340](https://policies.ncdhhs.gov/document/fns-340-deductions/) | rules/tables/fns.yaml |
| `fns.deductions.medical` | Deductions (medical deduction for elderly/disabled members) | [NC FNS Manual FNS 340](https://policies.ncdhhs.gov/document/fns-340-deductions/) | rules/tables/fns.yaml |
| `fns.deductions.shelter` | Deductions (excess shelter deduction) | [NC FNS Manual FNS 340](https://policies.ncdhhs.gov/document/fns-340-deductions/) | rules/tables/fns.yaml |
| `fns.deductions.standard` | Deductions (standard deduction) | [NC FNS Manual FNS 340](https://policies.ncdhhs.gov/document/fns-340-deductions/) | rules/tables/fns.yaml |
| `fns.elderly_disabled_exemption` | Rules for Budgeting Income (elderly/disabled households exempt from the gross income test) | [NC FNS Manual FNS 305](https://policies.ncdhhs.gov/document/fns-305-rules-for-budgeting-income/) | — |
| `fns.expedited` | Office operations and application processing (expedited service, 7-day decision) | [Federal SNAP Regulations 7 CFR 273.2(i)](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-II/subchapter-C/part-273/section-273.2) | rules/tables/fns.yaml |
| `fns.gross_income` | Rules for Budgeting Income (gross income test) | [NC FNS Manual FNS 305](https://policies.ncdhhs.gov/document/fns-305-rules-for-budgeting-income/) | rules/tables/fns.yaml |
| `fns.household_composition` | Household Composition | [NC FNS Manual FNS 210](https://policies.ncdhhs.gov/document/fns-210-household-composition/) | — |
| `fns.immigration` | Non-Citizen Requirements | [NC FNS Manual FNS 227](https://policies.ncdhhs.gov/document/fns-227-non-citizen-requirements/) | — |
| `fns.net_income` | Rules for Budgeting Income (net income test) | [NC FNS Manual FNS 305](https://policies.ncdhhs.gov/document/fns-305-rules-for-budgeting-income/) | rules/tables/fns.yaml |
| `lifeline.income` | Consumer qualification for Lifeline (income at or below 135% of poverty guidelines) | [FCC Lifeline Rules 47 CFR 54.409(a)(1)](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-54/subpart-E/section-54.409) | rules/tables/lifeline.yaml + fpl.yaml |
| `lifeline.qualifying_program` | Consumer qualification for Lifeline (participation in SNAP, Medicaid, SSI, or other programs) | [FCC Lifeline Rules 47 CFR 54.409(a)(2)](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-54/subpart-E/section-54.409) | rules/tables/lifeline.yaml |
| `medicaid.child` | Classification and Evaluation (Medicaid for Infants and Children coverage groups) | [NC Medicaid Family & Children's Medicaid Manual MA-3415](https://policies.ncdhhs.gov/document/ma-3415-classification-and-evaluation/) | rules/tables/medicaid.yaml + fpl.yaml |
| `medicaid.expansion_adult` | MAGI Adult (Medicaid Expansion) | [NC Medicaid Family & Children's Medicaid Manual MA-3236](https://policies.ncdhhs.gov/document/ma-3236-magi-adult-medicaid-expansion/) | rules/tables/medicaid.yaml + fpl.yaml |
| `medicaid.immigration` | Alien Requirements (qualified non-citizen eligibility) | [NC Medicaid Family & Children's Medicaid Manual MA-3330](https://policies.ncdhhs.gov/document/ma-3330-alien-requirements/) | — |
| `medicaid.magi_income` | Modified Adjusted Gross Income (MAGI) methodology | [NC Medicaid Family & Children's Medicaid Manual MA-3306](https://policies.ncdhhs.gov/document/ma-3306-modified-adjusted-gross-income-magi/) | rules/tables/medicaid.yaml |
| `medicaid.parent_caretaker` | Caretaker Relatives / Kinship | [NC Medicaid Family & Children's Medicaid Manual MA-3235](https://policies.ncdhhs.gov/document/ma-3235-caretaker-relatives-kinship/) | rules/tables/medicaid.yaml + fpl.yaml |
| `medicaid.pregnant` | Pregnant Woman Coverage | [NC Medicaid Family & Children's Medicaid Manual MA-3240](https://policies.ncdhhs.gov/document/ma-3240-pregnant-woman-coverage/) | rules/tables/medicaid.yaml + fpl.yaml |
| `wic.adjunctive` | Certification of participants (adjunctive income eligibility via Medicaid/SNAP/TANF enrollment) | [Federal WIC Regulations 7 CFR 246.7(d)(2)(vi)](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-II/subchapter-A/part-246/subpart-C/section-246.7) | — |
| `wic.categorical` | Certification of participants (categories: pregnant/postpartum women, infants, children under 5) | [Federal WIC Regulations 7 CFR 246.7(c)](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-II/subchapter-A/part-246/subpart-C/section-246.7) | — |
| `wic.income` | Certification of participants (income eligibility, 185% of poverty guidelines) | [Federal WIC Regulations 7 CFR 246.7(d)](https://www.ecfr.gov/current/title-7/subtitle-B/chapter-II/subchapter-A/part-246/subpart-C/section-246.7) | rules/tables/wic.yaml + fpl.yaml |

## Current table versions

- `rules/tables/fpl.yaml` — HHS ASPE 2026 Poverty Guidelines (48 contiguous states & DC); Federal Register 2026-01-15, FR Doc. 2026-00755 (effective 2026-01-13 → 2027-03-31)
- `rules/tables/fns.yaml` — USDA FNS SNAP FY2026 COLA Memo (effective 2025-10-01), 48 States & DC (effective 2025-10-01 → 2026-09-30)
- `rules/tables/medicaid.yaml` — NCDHHS MA-3321 MAGI Medicaid & Medicaid Expansion Income Limits (effective 2026-04-01) (effective 2026-04-01 → 2027-03-31)
- `rules/tables/wic.yaml` — 7 CFR 246.7(d)(1) WIC income eligibility standard (185% of poverty guidelines), 2026-2027 IEG cycle (effective 2026-07-01 → 2027-06-30)
- `rules/tables/lifeline.yaml` — 47 CFR 54.409(a)(1) income standard (135% of poverty guidelines); 47 CFR 54.403(a)(1) support amount (effective 2026-01-13 → 2027-03-31)

## Updating the annual numbers

The federal government adjusts these figures every year: FPL guidelines in
January, SNAP cost-of-living adjustments effective October 1. The engine's
numbers live in five YAML files — **updating them is a data pull request,
not a code change.**

1. Get the new source documents:
   - FPL: the HHS poverty guidelines page (linked from `rules/tables/fpl.yaml`).
   - FNS/SNAP: the USDA "SNAP Cost-of-Living Adjustments" memo for the new
     fiscal year (linked from `rules/tables/fns.yaml`).
   - Medicaid: NC DHHS MAGI percentage limits (linked from
     `rules/tables/medicaid.yaml`) — these change rarely.
   - WIC and Lifeline (`rules/tables/wic.yaml`, `rules/tables/lifeline.yaml`)
     store statutory percent-of-FPL multipliers and the Lifeline support
     amount; their dollar limits move automatically with `fpl.yaml`. Bump
     their `effective_from`/`effective_to` each cycle (WIC's IEG year runs
     July 1 → June 30) and confirm the regulations haven't changed.
2. Edit the YAML file(s): update every figure under `values:` (all money is
   **integer cents**), update `source_url`/`source_name`, and set the new
   `effective_from` / `effective_to` dates. The loader refuses to serve a
   table whose `effective_to` is in the past (`StaleTableError`), so a missed
   update fails loudly instead of screening with stale numbers.
3. Recompute the golden fixtures in `tests/fixtures/golden/*.yaml` by hand
   for the new figures, and set `verified: false` on any you changed until a
   second person re-checks them.
4. Run the suite: `uv run pytest`. The golden tests will disagree with your
   YAML edits until both are consistent — that disagreement is the safety
   check working.
5. Regenerate this file: `uv run python scripts/gen_rules_doc.py`.
6. Open a PR titled `data: FY20XX tables` containing only YAML, fixture, and
   docs changes. A reviewer verifies every figure against the source PDF
   before merge.
