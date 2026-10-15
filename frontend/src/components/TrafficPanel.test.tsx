import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { TrafficEntry } from '../api/types'
import { useStudio } from '../store'
import { frame } from '../test/fixtures'
import { TrafficPanel } from './TrafficPanel'

const initial = useStudio.getState()

function mockServer(saved: TrafficEntry[]) {
  const fetchMock = vi.fn(async (_url: string, init: RequestInit = {}) =>
    init.method === 'DELETE'
      ? new Response(null, { status: 204 })
      : new Response(JSON.stringify(saved), { status: 200 }),
  )
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const push = (e: TrafficEntry) =>
  act(() => useStudio.getState().handle({ type: 'traffic', data: e }))

const bodyRows = () => screen.getAllByRole('row').slice(1)

beforeEach(() => useStudio.setState(initial, true))
afterEach(() => vi.unstubAllGlobals())

describe('TrafficPanel', () => {
  it('loads saved frames, then adds live ones', async () => {
    mockServer([frame(1), frame(2)])
    render(<TrafficPanel onClose={() => {}} />)
    await waitFor(() => expect(bodyRows()).toHaveLength(2))
    push(frame(3, { exception_code: 2, direction: 'rx' }))
    expect(bodyRows()).toHaveLength(3)
    expect(bodyRows()[2]).toHaveTextContent('exception 02h Illegal data address')
    expect(bodyRows()[2]).toHaveClass('problem')
    expect(screen.getByTestId('traffic-counts')).toHaveTextContent(
      'TX 1 · RX 2 · exceptions 1 · malformed 0',
    )
  })

  it('pauses the view and counts what arrives meanwhile', async () => {
    mockServer([frame(1)])
    render(<TrafficPanel onClose={() => {}} />)
    await waitFor(() => expect(bodyRows()).toHaveLength(1))
    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    push(frame(2))
    push(frame(3))
    expect(bodyRows()).toHaveLength(1)
    expect(screen.getByTestId('traffic-counts')).toHaveTextContent('paused, 2 new frames')
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    expect(bodyRows()).toHaveLength(3)
  })

  it('filters errors only and clears on the server', async () => {
    const fetchMock = mockServer([frame(1), frame(2, { error: 'bad CRC 0000, expected CDC5' })])
    render(<TrafficPanel onClose={() => {}} />)
    await waitFor(() => expect(bodyRows()).toHaveLength(2))
    fireEvent.click(screen.getByLabelText(/Errors only/))
    expect(bodyRows()).toHaveLength(1)
    expect(bodyRows()[0]).toHaveTextContent('bad CRC')

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Clear' })))
    expect(fetchMock).toHaveBeenLastCalledWith('/api/traffic', expect.objectContaining({ method: 'DELETE' }))
    expect(screen.getByText('No frames yet.')).toBeInTheDocument()
  })
})
