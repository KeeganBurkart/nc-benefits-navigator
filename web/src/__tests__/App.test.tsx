import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { createSession, getReport } from '../api'
import { HOUSEHOLD, program, screening } from './fixtures'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return {
    ...mod,
    createSession: vi.fn(),
    getReport: vi.fn(),
    streamMessage: vi.fn(),
    patchHousehold: vi.fn(),
    deleteSession: vi.fn(),
  }
})

const mockCreate = vi.mocked(createSession)
const mockReport = vi.mocked(getReport)

describe('App', () => {
  beforeEach(() => {
    mockCreate.mockResolvedValue({ sessionId: 's1', demoMode: true })
    mockReport.mockResolvedValue({
      household: HOUSEHOLD,
      screening: screening([program({})]),
      generated_at: '2026-07-01T00:00:00Z',
    })
  })

  it('creates a session on load and renders both panes', async () => {
    render(<App />)
    expect((await screen.findAllByText('m1')).length).toBeGreaterThan(0)
    expect(mockCreate).toHaveBeenCalledTimes(1)
    expect(mockReport).toHaveBeenCalledWith('s1')
    expect(screen.getByLabelText('Message')).toBeTruthy()
    expect(screen.getByText('Likely eligible')).toBeTruthy()
  })

  it('shows the demo banner when X-Demo-Mode was set', async () => {
    render(<App />)
    expect(
      await screen.findByText(
        'Public demo — example data only. Do not enter real client information.',
      ),
    ).toBeTruthy()
  })

  it('renders the persistent footer disclaimer with an ePASS link', async () => {
    render(<App />)
    await screen.findAllByText('m1')
    const footer = document.querySelector('.app-footer')!
    expect(footer.textContent).toContain('not an eligibility determination')
    const link = footer.querySelector('a') as HTMLAnchorElement
    expect(link.href).toBe('https://epass.nc.gov/')
  })
})
