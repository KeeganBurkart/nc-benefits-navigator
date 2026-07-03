import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { ApiError } from '../api'
import type { Household, Patch } from '../types'

interface FactsPanelProps {
  household: Household | null
  onPatch: (patch: Patch) => Promise<void>
}

interface FieldError {
  loc: string
  message: string
}

const DEBOUNCE_MS = 500

const RELATIONSHIPS = ['self', 'spouse', 'child', 'other_relative', 'unrelated']
const IMMIGRATION = ['citizen', 'qualified_immigrant', 'not_qualified', 'unknown']
const KINDS = [
  'wages',
  'self_employment',
  'unemployment',
  'ssi',
  'ssdi',
  'social_security',
  'child_support_received',
  'other',
]
const FREQUENCIES = ['hourly', 'weekly', 'biweekly', 'semimonthly', 'monthly', 'yearly']

type ListItem = Record<string, unknown> & { id: string }

/** Deep-merge queued patches; members/income lists merge item objects by id. */
function mergePatches(patches: Patch[]): Patch {
  const merged: Patch = {}
  for (const patch of patches) {
    for (const [key, value] of Object.entries(patch)) {
      if ((key === 'members' || key === 'income') && Array.isArray(value)) {
        const list = [...((merged[key] as ListItem[]) ?? [])]
        for (const item of value as ListItem[]) {
          const idx = list.findIndex((x) => x.id === item.id)
          if (idx >= 0) list[idx] = { ...list[idx], ...item }
          else list.push(item)
        }
        merged[key] = list
      } else if (key === 'expenses' && typeof value === 'object' && value !== null) {
        merged.expenses = { ...((merged.expenses as object) ?? {}), ...value }
      } else {
        merged[key] = value
      }
    }
  }
  return merged
}

function parseBool(value: string): boolean | null {
  if (value === 'yes') return true
  if (value === 'no') return false
  return null
}

function boolValue(value: boolean | null): string {
  if (value === true) return 'yes'
  if (value === false) return 'no'
  return ''
}

function dollars(cents: number | null): string {
  return cents === null ? '' : String(cents / 100)
}

function parseNumber(value: string): number | null {
  if (value.trim() === '') return null
  const n = Number(value)
  return Number.isNaN(n) ? null : n
}

function nextId(prefix: string, existing: { id: string }[]): string {
  let n = existing.length + 1
  const ids = new Set(existing.map((x) => x.id))
  while (ids.has(`${prefix}${n}`)) n += 1
  return `${prefix}${n}`
}

// Controlled fields with a local draft overlay: the committed prop value is
// shown except while the user is mid-edit, so chat/server-driven household
// updates render immediately without clobbering in-progress typing. The draft
// clears on blur (by then the debounced PATCH has landed the edit in props).

interface DraftFieldProps {
  committed: string | number
  onEdit: (raw: string) => void
}

function DraftInput({
  committed,
  onEdit,
  ...rest
}: DraftFieldProps & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange'>) {
  const [draft, setDraft] = useState<string | null>(null)
  return (
    <input
      {...rest}
      value={draft ?? committed}
      onChange={(e) => {
        setDraft(e.target.value)
        onEdit(e.target.value)
      }}
      onBlur={() => setDraft(null)}
    />
  )
}

function DraftSelect({
  committed,
  onEdit,
  children,
  ...rest
}: DraftFieldProps & { children: ReactNode } & Omit<
    React.SelectHTMLAttributes<HTMLSelectElement>,
    'value' | 'onChange'
  >) {
  const [draft, setDraft] = useState<string | null>(null)
  return (
    <select
      {...rest}
      value={draft ?? committed}
      onChange={(e) => {
        setDraft(e.target.value)
        onEdit(e.target.value)
      }}
      onBlur={() => setDraft(null)}
    >
      {children}
    </select>
  )
}

function YesNoSelect({
  committed,
  onEdit,
  ...rest
}: { committed: boolean | null; onEdit: (value: boolean | null) => void } & Omit<
    React.SelectHTMLAttributes<HTMLSelectElement>,
    'value' | 'onChange'
  >) {
  return (
    <DraftSelect committed={boolValue(committed)} onEdit={(raw) => onEdit(parseBool(raw))} {...rest}>
      <option value="">—</option>
      <option value="yes">Yes</option>
      <option value="no">No</option>
    </DraftSelect>
  )
}

export default function FactsPanel({ household, onPatch }: FactsPanelProps) {
  const [error, setError] = useState<FieldError | null>(null)
  const pending = useRef<Patch[]>([])
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  async function submit(patch: Patch) {
    setError(null)
    try {
      await onPatch(patch)
    } catch (e) {
      if (e instanceof ApiError) {
        const m = e.message.match(/^([\w.[\]]+): (.*)$/s)
        setError(m ? { loc: m[1], message: m[2] } : { loc: '', message: e.message })
      } else {
        setError({ loc: '', message: (e as Error).message })
      }
    }
  }

  function flush() {
    const patches = pending.current
    pending.current = []
    if (patches.length) void submit(mergePatches(patches))
  }

  function queue(patch: Patch) {
    pending.current.push(patch)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(flush, DEBOUNCE_MS)
  }

  function immediate(patch: Patch) {
    window.clearTimeout(timer.current)
    pending.current.push(patch)
    flush()
  }

  if (!household) return <div className="facts-panel">Loading…</div>

  const { members, income, expenses } = household

  const errorFor = (...locs: string[]) =>
    error && locs.includes(error.loc) ? <div className="field-error">{error.message}</div> : null

  return (
    <div className="facts-panel">
      <h2>Household facts</h2>
      <p className="facts-hint">Everything here is editable — fix anything the assistant got wrong.</p>
      {error && error.loc === '' && <div className="field-error">{error.message}</div>}

      <h3>Household</h3>
      <div className="facts-grid">
        <label>
          County
          <DraftInput
            type="text"
            committed={household.county ?? ''}
            onEdit={(raw) => queue({ county: raw.trim() || null })}
          />
        </label>
        <label>
          Buys &amp; prepares food together
          <YesNoSelect
            committed={household.purchases_and_prepares_together}
            onEdit={(value) => queue({ purchases_and_prepares_together: value })}
          />
        </label>
        <label>
          No fixed home (homeless)
          <YesNoSelect
            committed={household.is_homeless}
            onEdit={(value) => queue({ is_homeless: value })}
          />
        </label>
        <label>
          Cash on hand ($, incl. bank accounts)
          <DraftInput
            type="number"
            step="0.01"
            min={0}
            committed={dollars(household.liquid_resources_cents)}
            onEdit={(raw) => queue({ liquid_resources: parseNumber(raw) })}
          />
          {errorFor('liquid_resources_cents')}
        </label>
        {errorFor('county', 'purchases_and_prepares_together', 'is_homeless')}
      </div>

      <h3>
        Members
        <button
          type="button"
          className="add-btn"
          onClick={() => immediate({ members: [{ id: nextId('m', members) }] })}
        >
          + Add member
        </button>
      </h3>
      {members.length === 0 ? (
        <p className="facts-empty">No members yet.</p>
      ) : (
        <table className="facts-table">
          <thead>
            <tr>
              <th>Person</th>
              <th>Age</th>
              <th>Relationship</th>
              <th>Pregnant</th>
              <th>Disabled</th>
              <th>Immigration</th>
              <th>Student</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {members.map((m, i) => (
              <tr key={m.id}>
                <td>{m.id}</td>
                <td>
                  <DraftInput
                    type="number"
                    aria-label={`age of ${m.id}`}
                    committed={m.age ?? ''}
                    min={0}
                    max={125}
                    onEdit={(raw) => queue({ members: [{ id: m.id, age: parseNumber(raw) }] })}
                  />
                  {errorFor(`members.${i}.age`)}
                </td>
                <td>
                  <DraftSelect
                    aria-label={`relationship of ${m.id}`}
                    committed={m.relationship ?? ''}
                    onEdit={(raw) => queue({ members: [{ id: m.id, relationship: raw || null }] })}
                  >
                    <option value="">—</option>
                    {RELATIONSHIPS.map((r) => (
                      <option key={r} value={r}>
                        {r.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </DraftSelect>
                </td>
                <td>
                  <YesNoSelect
                    aria-label={`pregnant ${m.id}`}
                    committed={m.is_pregnant}
                    onEdit={(value) => queue({ members: [{ id: m.id, is_pregnant: value }] })}
                  />
                </td>
                <td>
                  <YesNoSelect
                    aria-label={`disabled ${m.id}`}
                    committed={m.is_disabled}
                    onEdit={(value) => queue({ members: [{ id: m.id, is_disabled: value }] })}
                  />
                </td>
                <td>
                  <DraftSelect
                    aria-label={`immigration status of ${m.id}`}
                    committed={m.immigration_status ?? ''}
                    onEdit={(raw) =>
                      queue({ members: [{ id: m.id, immigration_status: raw || null }] })
                    }
                  >
                    <option value="">—</option>
                    {IMMIGRATION.map((s) => (
                      <option key={s} value={s}>
                        {s.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </DraftSelect>
                </td>
                <td>
                  <YesNoSelect
                    aria-label={`student ${m.id}`}
                    committed={m.is_student}
                    onEdit={(value) => queue({ members: [{ id: m.id, is_student: value }] })}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="remove-btn"
                    aria-label={`remove ${m.id}`}
                    onClick={() => immediate({ members: [{ id: m.id, _delete: true }] })}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>
        Income
        <button
          type="button"
          className="add-btn"
          onClick={() => immediate({ income: [{ id: nextId('i', income) }] })}
        >
          + Add income
        </button>
      </h3>
      {income.length === 0 ? (
        <p className="facts-empty">No income recorded.</p>
      ) : (
        <table className="facts-table">
          <thead>
            <tr>
              <th>Whose</th>
              <th>Type</th>
              <th>Amount ($)</th>
              <th>Frequency</th>
              <th>Hrs/wk</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {income.map((item, i) => (
              <tr key={item.id}>
                <td>
                  <DraftSelect
                    aria-label={`member for ${item.id}`}
                    committed={item.member_id ?? ''}
                    onEdit={(raw) => queue({ income: [{ id: item.id, member_id: raw || null }] })}
                  >
                    <option value="">—</option>
                    {members.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.id}
                      </option>
                    ))}
                  </DraftSelect>
                </td>
                <td>
                  <DraftSelect
                    aria-label={`kind of ${item.id}`}
                    committed={item.kind ?? ''}
                    onEdit={(raw) => queue({ income: [{ id: item.id, kind: raw || null }] })}
                  >
                    <option value="">—</option>
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {k.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </DraftSelect>
                </td>
                <td>
                  <DraftInput
                    type="number"
                    step="0.01"
                    min={0}
                    aria-label={`amount of ${item.id}`}
                    committed={dollars(item.amount_cents)}
                    onEdit={(raw) => queue({ income: [{ id: item.id, amount: parseNumber(raw) }] })}
                  />
                  {errorFor(`income.${i}.amount_cents`)}
                </td>
                <td>
                  <DraftSelect
                    aria-label={`frequency of ${item.id}`}
                    committed={item.frequency ?? ''}
                    onEdit={(raw) => queue({ income: [{ id: item.id, frequency: raw || null }] })}
                  >
                    <option value="">—</option>
                    {FREQUENCIES.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </DraftSelect>
                </td>
                <td>
                  {item.frequency === 'hourly' ? (
                    <DraftInput
                      type="number"
                      min={0}
                      aria-label={`hours per week of ${item.id}`}
                      committed={item.hours_per_week ?? ''}
                      onEdit={(raw) =>
                        queue({ income: [{ id: item.id, hours_per_week: parseNumber(raw) }] })
                      }
                    />
                  ) : (
                    '—'
                  )}
                  {errorFor(`income.${i}.hours_per_week`)}
                </td>
                <td>
                  <button
                    type="button"
                    className="remove-btn"
                    aria-label={`remove ${item.id}`}
                    onClick={() => immediate({ income: [{ id: item.id, _delete: true }] })}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h3>Expenses</h3>
      <div className="facts-grid">
        <label>
          Rent / mortgage ($/mo)
          <DraftInput
            type="number"
            step="0.01"
            min={0}
            committed={dollars(expenses.rent_or_mortgage_cents)}
            onEdit={(raw) => queue({ expenses: { rent_or_mortgage: parseNumber(raw) } })}
          />
          {errorFor('expenses.rent_or_mortgage_cents')}
        </label>
        <label>
          Utilities included in rent
          <YesNoSelect
            committed={expenses.utilities_included}
            onEdit={(value) => queue({ expenses: { utilities_included: value } })}
          />
        </label>
        <label>
          Pays heating / cooling
          <YesNoSelect
            committed={expenses.pays_heating_cooling}
            onEdit={(value) => queue({ expenses: { pays_heating_cooling: value } })}
          />
        </label>
        <label>
          Dependent care ($/mo)
          <DraftInput
            type="number"
            step="0.01"
            min={0}
            committed={dollars(expenses.dependent_care_cents)}
            onEdit={(raw) => queue({ expenses: { dependent_care: parseNumber(raw) } })}
          />
          {errorFor('expenses.dependent_care_cents')}
        </label>
        <label>
          Child support paid out ($/mo)
          <DraftInput
            type="number"
            step="0.01"
            min={0}
            committed={dollars(expenses.child_support_paid_cents)}
            onEdit={(raw) => queue({ expenses: { child_support_paid: parseNumber(raw) } })}
          />
          {errorFor('expenses.child_support_paid_cents')}
        </label>
        <label>
          Medical expenses, elderly/disabled ($/mo)
          <DraftInput
            type="number"
            step="0.01"
            min={0}
            committed={dollars(expenses.medical_expenses_elderly_disabled_cents)}
            onEdit={(raw) =>
              queue({ expenses: { medical_expenses_elderly_disabled: parseNumber(raw) } })
            }
          />
          {errorFor('expenses.medical_expenses_elderly_disabled_cents')}
        </label>
      </div>
    </div>
  )
}
