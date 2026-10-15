import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { WriteLogEntry } from '../api/types'
import { useStudio } from '../store'
import { WriteLogPanel } from './WriteLogPanel'

const initial = useStudio.getState()

const entry = (seq: number, over: Partial<WriteLogEntry> = {}): WriteLogEntry => ({
  seq,
  timestamp: 1_760_000_000 + seq,
  connection_id: 'c1',
  connection_name: 'Plant',
  device_id: 1,
  function: 6,
  address: 100,
  poll_id: 'w1',
  alias: 'setpoint',
  unit: '°C',
  old: '21.5',
  new: '23.4',
  values: [234],
  ok: true,
  error: null,
  ...over,
})

beforeEach(() => useStudio.setState(initial, true))
afterEach(() => vi.unstubAllGlobals())

function mockList(entries: WriteLogEntry[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(entries), { status: 200 })),
  )
}

describe('WriteLogPanel', () => {
  it('shows saved writes with old and new values', async () => {
    mockList([
      entry(2, { ok: false, error: 'Illegal data address (02h)', old: null, poll_id: null }),
      entry(1),
    ])
    render(<WriteLogPanel onClose={() => {}} />)
    await screen.findByText('2 entries · newest first')
    const rows = screen.getAllByRole('row')
    // header + 2 entries, newest first
    expect(rows).toHaveLength(3)
    expect(within(rows[1]).getByText('Illegal data address (02h)')).toBeInTheDocument()
    expect(rows[1]).toHaveClass('failed')
    expect(rows[2]).toHaveTextContent('21.5 °C → 23.4 °C')
    expect(rows[2]).toHaveTextContent('setpoint')
    expect(rows[2]).toHaveTextContent('OK')
  })

  it('adds writes pushed over the WebSocket on top', async () => {
    mockList([entry(1)])
    render(<WriteLogPanel onClose={() => {}} />)
    await screen.findByText('1 entries · newest first')
    act(() => useStudio.getState().handle({ type: 'write', data: entry(2, { new: '30' }) }))
    // A duplicate (same seq) is ignored.
    act(() => useStudio.getState().handle({ type: 'write', data: entry(2, { new: '30' }) }))
    const rows = screen.getAllByRole('row')
    expect(rows).toHaveLength(3)
    expect(rows[1]).toHaveTextContent('→ 30 °C')
  })
})
