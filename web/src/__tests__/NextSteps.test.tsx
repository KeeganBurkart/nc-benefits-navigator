import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import NextSteps from '../components/NextSteps'
import { buildCaseNote } from '../lib'
import { CITATION, program, screening } from './fixtures'

const expeditedReason = {
  rule_id: 'fns.expedited',
  text: 'This household appears to qualify for EXPEDITED food assistance.',
  citation: CITATION,
}

describe('NextSteps', () => {
  it('renders nothing for an ordinary eligible screening', () => {
    const { container } = render(<NextSteps screening={screening([program({})])} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows the urgent food-help note when the expedited flag is present', () => {
    const s = screening([program({ reasons: [expeditedReason] })])
    render(<NextSteps screening={s} />)
    expect(screen.getByText(/food help/)).toBeTruthy()
    expect(screen.getByText(/NC 211/)).toBeTruthy()
  })

  it('shows the resource list when every program is likely ineligible', () => {
    const s = screening([
      program({ status: 'likely_ineligible', estimated_benefit_cents: null }),
      program({ program: 'medicaid', status: 'likely_ineligible', estimated_benefit_cents: null }),
    ])
    render(<NextSteps screening={s} />)
    expect(screen.getByText(/where to point this household next/)).toBeTruthy()
    expect(screen.getByText('Legal Aid of North Carolina')).toBeTruthy()
    expect(screen.getByText('NC 211')).toBeTruthy()
  })

  it('stays hidden while any program is still undecided', () => {
    const s = screening([
      program({ status: 'likely_ineligible', estimated_benefit_cents: null }),
      program({ program: 'medicaid', status: 'needs_more_info', estimated_benefit_cents: null }),
    ])
    const { container } = render(<NextSteps screening={s} />)
    expect(container.firstChild).toBeNull()
  })
})

describe('buildCaseNote', () => {
  it('summarizes programs, benefit, and the disclaimer deterministically', () => {
    const s = screening([program({}), program({ program: 'medicaid', status: 'needs_more_info', estimated_benefit_cents: null })])
    const note = buildCaseNote(s, new Date('2026-07-03T12:00:00'))
    expect(note).toContain('Jul 3, 2026')
    expect(note).toContain('household of 1, New Hanover County')
    expect(note).toContain('likely eligible (est. $291/mo)')
    expect(note).toContain('more info needed')
    expect(note).toContain('determined by county DSS')
    expect(note).not.toContain('undefined')
  })

  it('mentions the expedited flag when present', () => {
    const s = screening([program({ reasons: [expeditedReason] })])
    expect(buildCaseNote(s, new Date('2026-07-03T12:00:00'))).toContain('expedited FNS service')
  })
})
