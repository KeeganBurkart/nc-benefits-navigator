import { useEffect, useRef, useState } from 'react'
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
          <input
            key={`county-${household.county ?? ''}`}
            type="text"
            defaultValue={household.county ?? ''}
            onChange={(e) => queue({ county: e.target.value.trim() || null })}
          />
        </label>
        <label>
          Buys &amp; prepares food together
          <select
            defaultValue={boolValue(household.purchases_and_prepares_together)}
            onChange={(e) => queue({ purchases_and_prepares_together: parseBool(e.target.value) })}
          >
            <option value="">—</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
        {errorFor('county', 'purchases_and_prepares_together')}
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
                  <input
                    type="number"
                    aria-label={`age of ${m.id}`}
                    defaultValue={m.age ?? ''}
                    min={0}
                    max={125}
                    onChange={(e) =>
                      queue({ members: [{ id: m.id, age: parseNumber(e.target.value) }] })
                    }
                  />
                  {errorFor(`members.${i}.age`)}
                </td>
                <td>
                  <select
                    aria-label={`relationship of ${m.id}`}
                    defaultValue={m.relationship ?? ''}
                    onChange={(e) =>
                      queue({ members: [{ id: m.id, relationship: e.target.value || null }] })
                    }
                  >
                    <option value="">—</option>
                    {RELATIONSHIPS.map((r) => (
                      <option key={r} value={r}>
                        {r.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`pregnant ${m.id}`}
                    defaultValue={boolValue(m.is_pregnant)}
                    onChange={(e) =>
                      queue({ members: [{ id: m.id, is_pregnant: parseBool(e.target.value) }] })
                    }
                  >
                    <option value="">—</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`disabled ${m.id}`}
                    defaultValue={boolValue(m.is_disabled)}
                    onChange={(e) =>
                      queue({ members: [{ id: m.id, is_disabled: parseBool(e.target.value) }] })
                    }
                  >
                    <option value="">—</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`immigration status of ${m.id}`}
                    defaultValue={m.immigration_status ?? ''}
                    onChange={(e) =>
                      queue({
                        members: [{ id: m.id, immigration_status: e.target.value || null }],
                      })
                    }
                  >
                    <option value="">—</option>
                    {IMMIGRATION.map((s) => (
                      <option key={s} value={s}>
                        {s.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`student ${m.id}`}
                    defaultValue={boolValue(m.is_student)}
                    onChange={(e) =>
                      queue({ members: [{ id: m.id, is_student: parseBool(e.target.value) }] })
                    }
                  >
                    <option value="">—</option>
                    <option value="yes">Yes</option>
                    <option value="no">No</option>
                  </select>
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
                  <select
                    aria-label={`member for ${item.id}`}
                    defaultValue={item.member_id ?? ''}
                    onChange={(e) =>
                      queue({ income: [{ id: item.id, member_id: e.target.value || null }] })
                    }
                  >
                    <option value="">—</option>
                    {members.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.id}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    aria-label={`kind of ${item.id}`}
                    defaultValue={item.kind ?? ''}
                    onChange={(e) =>
                      queue({ income: [{ id: item.id, kind: e.target.value || null }] })
                    }
                  >
                    <option value="">—</option>
                    {KINDS.map((k) => (
                      <option key={k} value={k}>
                        {k.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    type="number"
                    step="0.01"
                    min={0}
                    aria-label={`amount of ${item.id}`}
                    defaultValue={dollars(item.amount_cents)}
                    onChange={(e) =>
                      queue({ income: [{ id: item.id, amount: parseNumber(e.target.value) }] })
                    }
                  />
                  {errorFor(`income.${i}.amount_cents`)}
                </td>
                <td>
                  <select
                    aria-label={`frequency of ${item.id}`}
                    defaultValue={item.frequency ?? ''}
                    onChange={(e) =>
                      queue({ income: [{ id: item.id, frequency: e.target.value || null }] })
                    }
                  >
                    <option value="">—</option>
                    {FREQUENCIES.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  {item.frequency === 'hourly' ? (
                    <input
                      type="number"
                      min={0}
                      aria-label={`hours per week of ${item.id}`}
                      defaultValue={item.hours_per_week ?? ''}
                      onChange={(e) =>
                        queue({
                          income: [{ id: item.id, hours_per_week: parseNumber(e.target.value) }],
                        })
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
          <input
            type="number"
            step="0.01"
            min={0}
            defaultValue={dollars(expenses.rent_or_mortgage_cents)}
            onChange={(e) =>
              queue({ expenses: { rent_or_mortgage: parseNumber(e.target.value) } })
            }
          />
          {errorFor('expenses.rent_or_mortgage_cents')}
        </label>
        <label>
          Utilities included in rent
          <select
            defaultValue={boolValue(expenses.utilities_included)}
            onChange={(e) => queue({ expenses: { utilities_included: parseBool(e.target.value) } })}
          >
            <option value="">—</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
        <label>
          Pays heating / cooling
          <select
            defaultValue={boolValue(expenses.pays_heating_cooling)}
            onChange={(e) =>
              queue({ expenses: { pays_heating_cooling: parseBool(e.target.value) } })
            }
          >
            <option value="">—</option>
            <option value="yes">Yes</option>
            <option value="no">No</option>
          </select>
        </label>
        <label>
          Dependent care ($/mo)
          <input
            type="number"
            step="0.01"
            min={0}
            defaultValue={dollars(expenses.dependent_care_cents)}
            onChange={(e) => queue({ expenses: { dependent_care: parseNumber(e.target.value) } })}
          />
          {errorFor('expenses.dependent_care_cents')}
        </label>
        <label>
          Child support paid out ($/mo)
          <input
            type="number"
            step="0.01"
            min={0}
            defaultValue={dollars(expenses.child_support_paid_cents)}
            onChange={(e) =>
              queue({ expenses: { child_support_paid: parseNumber(e.target.value) } })
            }
          />
          {errorFor('expenses.child_support_paid_cents')}
        </label>
        <label>
          Medical expenses, elderly/disabled ($/mo)
          <input
            type="number"
            step="0.01"
            min={0}
            defaultValue={dollars(expenses.medical_expenses_elderly_disabled_cents)}
            onChange={(e) =>
              queue({
                expenses: { medical_expenses_elderly_disabled: parseNumber(e.target.value) },
              })
            }
          />
          {errorFor('expenses.medical_expenses_elderly_disabled_cents')}
        </label>
      </div>
    </div>
  )
}
