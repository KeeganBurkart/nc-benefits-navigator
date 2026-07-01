import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ResultsCards from '../components/ResultsCards'
import { CITATION, program, screening } from './fixtures'

describe('ResultsCards', () => {
  it('maps statuses to pills', () => {
    render(
      <ResultsCards
        screening={screening([
          program({ program: 'fns', status: 'likely_eligible' }),
          program({
            program: 'medicaid',
            program_label: 'NC Medicaid',
            status: 'needs_more_info',
            estimated_benefit_cents: null,
          }),
        ])}
      />,
    )
    expect(screen.getByText('Likely eligible').className).toContain('pill-likely_eligible')
    expect(screen.getByText('More info needed').className).toContain('pill-needs_more_info')
  })

  it('shows the ineligible pill', () => {
    render(<ResultsCards screening={screening([program({ status: 'likely_ineligible' })])} />)
    expect(screen.getByText('Likely not eligible').className).toContain('pill-likely_ineligible')
  })

  it('formats the estimated benefit from cents', () => {
    render(<ResultsCards screening={screening([program({ estimated_benefit_cents: 29100 })])} />)
    expect(screen.getByText('$291/month estimated')).toBeTruthy()
  })

  it('renders each reason with a citation link', () => {
    render(<ResultsCards screening={screening([program({})])} />)
    const link = screen.getByRole('link', { name: '[1]' }) as HTMLAnchorElement
    expect(link.href).toBe(CITATION.url)
    expect(link.title).toContain(CITATION.section)
  })

  it('renders missing fields as plain questions with raw-path fallback', () => {
    render(
      <ResultsCards
        screening={screening([
          program({
            status: 'needs_more_info',
            missing_fields: ['expenses.rent_or_mortgage_cents', 'some.unknown_path'],
          }),
        ])}
      />,
    )
    expect(screen.getByText('What is the rent or mortgage payment?')).toBeTruthy()
    expect(screen.getByText('some.unknown_path')).toBeTruthy()
  })
})
