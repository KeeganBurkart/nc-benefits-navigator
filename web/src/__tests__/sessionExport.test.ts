import { describe, expect, it } from 'vitest'
import { buildSessionExport, parseSessionImport } from '../lib'
import { HOUSEHOLD } from './fixtures'

describe('session export/import', () => {
  it('round-trips a household through export and import', () => {
    const payload = buildSessionExport(HOUSEHOLD)
    expect(payload.kind).toBe('session-export')
    expect(payload.app).toBe('nc-benefits-navigator')
    const parsed = parseSessionImport(JSON.stringify(payload))
    expect(parsed).toEqual(HOUSEHOLD)
  })

  it('rejects non-JSON with a friendly message', () => {
    expect(() => parseSessionImport('not json {')).toThrow('not valid JSON')
  })

  it('rejects JSON that is not a session export', () => {
    expect(() => parseSessionImport('{"foo": 1}')).toThrow('not a Benefits Navigator session export')
    expect(() => parseSessionImport('null')).toThrow('not a Benefits Navigator session export')
  })

  it('rejects an export whose household is malformed', () => {
    const bad = { app: 'nc-benefits-navigator', kind: 'session-export', version: 1, household: {} }
    expect(() => parseSessionImport(JSON.stringify(bad))).toThrow('missing its household data')
  })
})
