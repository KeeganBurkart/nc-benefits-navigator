import { DISCLAIMER } from '../lib'
import type { CitationOut, Household, ProgramResult, ScreeningResult } from '../types'

export const HOUSEHOLD: Household = {
  members: [
    {
      id: 'm1',
      age: 30,
      relationship: 'self',
      is_pregnant: false,
      is_disabled: false,
      immigration_status: 'citizen',
      is_student: false,
    },
  ],
  income: [
    {
      id: 'i1',
      member_id: 'm1',
      kind: 'wages',
      amount_cents: 125050,
      frequency: 'monthly',
      hours_per_week: null,
    },
  ],
  expenses: {
    rent_or_mortgage_cents: 90000,
    utilities_included: false,
    pays_heating_cooling: true,
    dependent_care_cents: null,
    child_support_paid_cents: null,
    medical_expenses_elderly_disabled_cents: null,
  },
  county: 'New Hanover',
  purchases_and_prepares_together: true,
}

export const CITATION: CitationOut = {
  rule_id: 'fns_gross_income_limit',
  manual: 'FNS 810',
  section: '810.02',
  title: 'Gross Income Limits',
  url: 'https://example.com/fns-810',
}

export function program(over: Partial<ProgramResult>): ProgramResult {
  return {
    program: 'fns',
    program_label: 'FNS (Food and Nutrition Services / SNAP)',
    status: 'likely_eligible',
    reasons: [
      { rule_id: 'fns_gross_income_limit', text: 'Income is under the limit.', citation: CITATION },
    ],
    estimated_benefit_cents: 29100,
    required_documents: [{ name: 'Pay stubs', why: 'Verify wages', rule_id: 'fns_income_docs' }],
    missing_fields: [],
    income_margin: null,
    ...over,
  }
}

export function screening(programs: ProgramResult[]): ScreeningResult {
  return {
    programs,
    household: HOUSEHOLD,
    missing_fields: [],
    generated_disclaimer: DISCLAIMER,
  }
}
