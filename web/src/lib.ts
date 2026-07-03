import type { Household, IncomeMargin, ScreeningResult, Status } from './types'

// Must match rules.engine.DISCLAIMER exactly.
export const DISCLAIMER =
  'This is a screening estimate, not an eligibility determination. ' +
  'Only your county DSS can determine eligibility. Apply online at https://epass.nc.gov.'

export const EPASS_URL = 'https://epass.nc.gov'

export const STATUS_LABELS: Record<Status, string> = {
  likely_eligible: 'Likely eligible',
  likely_ineligible: 'Likely not eligible',
  needs_more_info: 'More info needed',
}

/** Format integer cents as dollars: 29100 → "$291", 125050 → "$1,250.50". */
export function centsToDollars(cents: number): string {
  const dollars = cents / 100
  return dollars.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: cents % 100 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  })
}

export interface ChecklistEntry {
  name: string
  why: string
  programs: string[]
}

/** Deduplicate required documents across programs by document name. */
export function buildChecklist(screening: ScreeningResult): ChecklistEntry[] {
  const byName = new Map<string, ChecklistEntry>()
  for (const program of screening.programs) {
    for (const doc of program.required_documents) {
      const entry = byName.get(doc.name)
      if (entry) {
        if (!entry.programs.includes(program.program_label)) {
          entry.programs.push(program.program_label)
        }
      } else {
        byName.set(doc.name, { name: doc.name, why: doc.why, programs: [program.program_label] })
      }
    }
  }
  return [...byName.values()]
}

// Human phrasing for missing-field dotted paths. Paths look like
// members[<id>].<field>, income[<idx>].<field>, expenses.<field>, or <field>.
const LEAF_QUESTIONS: Record<string, string> = {
  age: 'How old is this person?',
  relationship: 'How is this person related to the applicant?',
  is_pregnant: 'Is anyone in the household pregnant?',
  is_disabled: 'Does this person have a disability?',
  immigration_status: "What is this person's citizenship or immigration status?",
  is_student: 'Is this person a student?',
  kind: 'What type of income is this?',
  amount_cents: 'How much is this income?',
  frequency: 'How often is this income received?',
  hours_per_week: 'How many hours per week does this person work?',
  rent_or_mortgage_cents: 'What is the rent or mortgage payment?',
  utilities_included: 'Are utilities included in the rent?',
  pays_heating_cooling: 'Does the household pay for heating or cooling?',
  dependent_care_cents: 'How much does the household pay for child or dependent care?',
  child_support_paid_cents: 'How much child support does anyone pay out?',
  medical_expenses_elderly_disabled_cents:
    'How much are medical expenses for elderly or disabled members?',
  county: 'What NC county does the household live in?',
  purchases_and_prepares_together: 'Does everyone buy and prepare food together?',
  is_homeless: 'Does the household have a fixed place to live?',
  liquid_resources_cents: 'How much cash does the household have on hand, including bank accounts?',
  members: 'Who is in the household?',
}

export function missingFieldQuestion(path: string): string {
  const leaf = path.split('.').pop() ?? path
  const question = LEAF_QUESTIONS[leaf]
  if (!question) return path
  const idMatch = path.match(/^members\[([^\]]+)\]\./)
  if (idMatch) return `${question} (${idMatch[1]})`
  return question
}

/** One-line distance-to-limit readout, e.g.
 * "Counted income is $660/month under the FNS gross income limit (…)". */
export function marginSummary(m: IncomeMargin): string {
  if (m.margin_cents === 0) return `Counted income is exactly at the ${m.test_label}.`
  const amount = centsToDollars(Math.abs(m.margin_cents))
  const direction = m.margin_cents > 0 ? 'under' : 'over'
  return `Counted income is ${amount}/month ${direction} the ${m.test_label}.`
}

// ---- Case-note summary (deterministic; no LLM involved) ----

/** One paragraph a worker can paste into their agency's case-management
 * system. Deliberately contains no identifying details beyond what the
 * screening itself used. */
export function buildCaseNote(screening: ScreeningResult, now: Date = new Date()): string {
  const date = now.toLocaleDateString('en-US', { dateStyle: 'medium' })
  const hh = screening.household
  const parts: string[] = []
  parts.push(
    `Benefits screening completed ${date} using NC Benefits Navigator ` +
      `(household of ${hh.members.length}${hh.county ? `, ${hh.county} County` : ''}).`,
  )
  for (const p of screening.programs) {
    let line = `${p.program_label}: ${STATUS_LABELS[p.status].toLowerCase()}`
    if (p.estimated_benefit_cents !== null) {
      line += ` (est. ${centsToDollars(p.estimated_benefit_cents)}/mo)`
    }
    parts.push(line + '.')
  }
  const expedited = screening.programs.some((p) =>
    p.reasons.some((r) => r.rule_id === 'fns.expedited'),
  )
  if (expedited) {
    parts.push('Household flagged for expedited FNS service (7-day decision).')
  }
  if (screening.missing_fields.length > 0) {
    parts.push(`Information still needed: ${screening.missing_fields.length} item(s).`)
  }
  parts.push(
    'Client given plain-language action plan and document checklist. ' +
      'Screening estimate only — eligibility is determined by county DSS.',
  )
  return parts.join(' ')
}

// ---- Session export / import (client-side only; nothing persists) ----

export interface SessionExport {
  app: 'nc-benefits-navigator'
  kind: 'session-export'
  version: 1
  exported_at: string
  household: Household
}

export function buildSessionExport(household: Household): SessionExport {
  return {
    app: 'nc-benefits-navigator',
    kind: 'session-export',
    version: 1,
    exported_at: new Date().toISOString(),
    household,
  }
}

/** Parse an exported session file. Throws Error with a user-facing message. */
export function parseSessionImport(text: string): Household {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    throw new Error('That file is not valid JSON.')
  }
  const payload = parsed as Partial<SessionExport> | null
  if (!payload || typeof payload !== 'object' || payload.kind !== 'session-export') {
    throw new Error('That file is not a Benefits Navigator session export.')
  }
  const hh = payload.household
  if (!hh || typeof hh !== 'object' || !Array.isArray(hh.members) || !Array.isArray(hh.income)) {
    throw new Error('The session file is missing its household data.')
  }
  return hh
}
