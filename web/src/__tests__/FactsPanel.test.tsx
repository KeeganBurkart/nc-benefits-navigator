import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import FactsPanel from '../components/FactsPanel'
import { HOUSEHOLD } from './fixtures'

describe('FactsPanel', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders the household', () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    expect(screen.getAllByText('m1').length).toBeGreaterThan(0)
    expect(screen.getByDisplayValue('New Hanover')).toBeTruthy()
    // income amount displayed as dollars
    expect((screen.getByLabelText('amount of i1') as HTMLInputElement).value).toBe('1250.5')
  })

  it('debounces edits and fires PATCH after 500ms', async () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    fireEvent.change(screen.getByLabelText('age of m1'), { target: { value: '31' } })
    expect(onPatch).not.toHaveBeenCalled()
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(onPatch).toHaveBeenCalledWith({ members: [{ id: 'm1', age: 31 }] })
  })

  it('sends income amounts in dollars', async () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    fireEvent.change(screen.getByLabelText('amount of i1'), { target: { value: '1300.75' } })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(onPatch).toHaveBeenCalledWith({ income: [{ id: 'i1', amount: 1300.75 }] })
  })

  it('sends expense edits with dollar keys', async () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    fireEvent.change(screen.getByLabelText(/Rent \/ mortgage/), { target: { value: '950' } })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(onPatch).toHaveBeenCalledWith({ expenses: { rent_or_mortgage: 950 } })
  })

  it('merges rapid edits into one PATCH', async () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    fireEvent.change(screen.getByLabelText('age of m1'), { target: { value: '31' } })
    vi.advanceTimersByTime(300)
    fireEvent.change(screen.getByLabelText('pregnant m1'), { target: { value: 'yes' } })
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(onPatch).toHaveBeenCalledTimes(1)
    expect(onPatch).toHaveBeenCalledWith({ members: [{ id: 'm1', age: 31, is_pregnant: true }] })
  })

  it('removes rows immediately with _delete', () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    fireEvent.click(screen.getByLabelText('remove i1'))
    expect(onPatch).toHaveBeenCalledWith({ income: [{ id: 'i1', _delete: true }] })
  })

  it('adds a member with a fresh id', () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    fireEvent.click(screen.getByText('+ Add member'))
    expect(onPatch).toHaveBeenCalledWith({ members: [{ id: 'm2' }] })
  })

  it('re-renders a field when the household prop changes (chat-recorded fact)', () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    const { rerender } = render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    const buysPrepares = () =>
      screen.getByLabelText(/Buys & prepares food together/) as HTMLSelectElement
    expect(buysPrepares().value).toBe('yes')

    // The server records purchases_and_prepares_together=false via the chat;
    // App passes the fresh household down. The select must show it.
    rerender(
      <FactsPanel
        household={{ ...HOUSEHOLD, purchases_and_prepares_together: false }}
        onPatch={onPatch}
      />,
    )
    expect(buysPrepares().value).toBe('no')

    // Same for already-rendered inputs (age was the observed stale field class).
    rerender(
      <FactsPanel
        household={{
          ...HOUSEHOLD,
          purchases_and_prepares_together: false,
          members: [{ ...HOUSEHOLD.members[0], age: 62 }],
        }}
        onPatch={onPatch}
      />,
    )
    expect((screen.getByLabelText('age of m1') as HTMLInputElement).value).toBe('62')
  })

  it('does not clobber a user edit in progress when the household prop changes', async () => {
    const onPatch = vi.fn().mockResolvedValue(undefined)
    const { rerender } = render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    const county = () => screen.getByDisplayValue(/Dur|New Hanover|Wake/) as HTMLInputElement

    // User is mid-keystroke in the county field…
    fireEvent.change(screen.getByDisplayValue('New Hanover'), { target: { value: 'Dur' } })
    expect(county().value).toBe('Dur')

    // …while an unrelated chat update re-renders the panel. The draft wins.
    rerender(<FactsPanel household={{ ...HOUSEHOLD, county: 'Wake' }} onPatch={onPatch} />)
    expect(county().value).toBe('Dur')

    // Once the user leaves the field, the committed value shows again.
    fireEvent.blur(county())
    expect(county().value).toBe('Wake')

    // And the edit itself was queued for PATCH, not lost.
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(onPatch).toHaveBeenCalledWith({ county: 'Dur' })
  })

  it('renders a 422 validation error inline at the offending field', async () => {
    const onPatch = vi
      .fn()
      .mockRejectedValue(new ApiError('members.0.age: age must be between 0 and 125 inclusive', 422))
    render(<FactsPanel household={HOUSEHOLD} onPatch={onPatch} />)
    fireEvent.change(screen.getByLabelText('age of m1'), { target: { value: '999' } })
    await act(async () => {
      vi.advanceTimersByTime(500)
      await Promise.resolve()
    })
    const cell = screen.getByLabelText('age of m1').closest('td')!
    expect(cell.textContent).toContain('age must be between 0 and 125 inclusive')
  })
})
