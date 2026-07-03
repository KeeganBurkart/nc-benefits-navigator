import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ResultsCards from '../components/ResultsCards'
import { marginSummary } from '../lib'
import { program, screening } from './fixtures'

describe('income margin readout', () => {
  it('renders headroom under the limit with the under styling', () => {
    const s = screening([
      program({
        income_margin: {
          test_label: 'FNS gross income limit (200% FPL, household of 1)',
          limit_cents: 266000,
          income_cents: 200000,
          margin_cents: 66000,
        },
      }),
    ])
    render(<ResultsCards screening={s} />)
    const line = screen.getByText(/\$660\/month under the FNS gross income limit/)
    expect(line.className).toContain('income-margin-under')
  })

  it('renders an over-limit margin with the over styling', () => {
    const s = screening([
      program({
        status: 'likely_ineligible',
        estimated_benefit_cents: null,
        income_margin: {
          test_label: 'WIC income limit (185% FPL, household of 2)',
          limit_cents: 333616,
          income_cents: 350000,
          margin_cents: -16384,
        },
      }),
    ])
    render(<ResultsCards screening={s} />)
    const line = screen.getByText(/\$163\.84\/month over the WIC income limit/)
    expect(line.className).toContain('income-margin-over')
  })

  it('renders nothing when the margin is null', () => {
    const s = screening([program({ income_margin: null })])
    const { container } = render(<ResultsCards screening={s} />)
    expect(container.querySelector('.income-margin')).toBeNull()
  })

  it('marginSummary says "exactly at" for a zero margin', () => {
    expect(
      marginSummary({ test_label: 'the limit', limit_cents: 1, income_cents: 1, margin_cents: 0 }),
    ).toContain('exactly at')
  })
})
