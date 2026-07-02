// TypeScript mirrors of the Python API shapes. Field names match the
// server's model_dump() output exactly (snake_case — do not camelize).

export type Relationship = 'self' | 'spouse' | 'child' | 'other_relative' | 'unrelated'
export type ImmigrationStatus = 'citizen' | 'qualified_immigrant' | 'not_qualified' | 'unknown'
export type IncomeKind =
  | 'wages'
  | 'self_employment'
  | 'unemployment'
  | 'ssi'
  | 'ssdi'
  | 'social_security'
  | 'child_support_received'
  | 'other'
export type Frequency = 'hourly' | 'weekly' | 'biweekly' | 'semimonthly' | 'monthly' | 'yearly'

export interface Member {
  id: string
  age: number | null
  relationship: Relationship | null
  is_pregnant: boolean | null
  is_disabled: boolean | null
  immigration_status: ImmigrationStatus | null
  is_student: boolean | null
}

export interface IncomeItem {
  id: string
  member_id: string | null
  kind: IncomeKind | null
  amount_cents: number | null
  frequency: Frequency | null
  hours_per_week: number | null
}

export interface Expenses {
  rent_or_mortgage_cents: number | null
  utilities_included: boolean | null
  pays_heating_cooling: boolean | null
  dependent_care_cents: number | null
  child_support_paid_cents: number | null
  medical_expenses_elderly_disabled_cents: number | null
}

export interface Household {
  members: Member[]
  income: IncomeItem[]
  expenses: Expenses
  county: string | null
  purchases_and_prepares_together: boolean | null
}

export type Status = 'likely_eligible' | 'likely_ineligible' | 'needs_more_info'

export interface CitationOut {
  rule_id: string
  manual: string
  section: string
  title: string
  url: string
}

export interface Reason {
  rule_id: string
  text: string
  citation: CitationOut
}

export interface DocumentRequirement {
  name: string
  why: string
  rule_id: string
}

export interface ProgramResult {
  program: 'fns' | 'medicaid' | 'wic' | 'lifeline'
  program_label: string
  status: Status
  reasons: Reason[]
  estimated_benefit_cents: number | null
  required_documents: DocumentRequirement[]
  missing_fields: string[]
}

export interface ScreeningResult {
  programs: ProgramResult[]
  household: Household
  missing_fields: string[]
  generated_disclaimer: string
}

export interface Report {
  household: Household
  screening: ScreeningResult
  generated_at: string
}

export type SseEvent =
  | { type: 'text'; delta: string }
  | { type: 'household'; data: Household }
  | { type: 'screening'; data: ScreeningResult }
  | { type: 'done' }
  | { type: 'error'; message: string }

// A household patch in the server's dollar-denominated patch dialect:
// income items use `amount` (dollars), expenses use unsuffixed dollar keys.
export type Patch = Record<string, unknown>
