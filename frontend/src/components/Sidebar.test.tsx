import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConnectionView } from '../api/types'
import { useStudio } from '../store'
import { Sidebar } from './Sidebar'

const initial = useStudio.getState()

const view = (state: ConnectionView['state'], last_error: string | null): ConnectionView => ({
  config: {
    type: 'tcp',
    id: 'c1',
    name: 'Plant',
    host: 'modbus-studio-sim',
    port: 5020,
    timeout_s: 1,
    retries: 0,
    delay_between_requests_ms: 0,
  },
  state,
  stats: { responses: 0, timeouts: 0, exceptions: 0 },
  last_error,
})

beforeEach(() => useStudio.setState(initial, true))
afterEach(() => vi.unstubAllGlobals())

describe('Sidebar', () => {
  it('explains why a connection is down', () => {
    useStudio.getState().upsertConnection(view('disconnected', "cannot resolve host 'modbus-studio-sim'"))
    render(<Sidebar />)
    expect(screen.getByText("cannot resolve host 'modbus-studio-sim'")).toBeInTheDocument()
  })

  it('hides a stale error once connected', () => {
    useStudio.getState().upsertConnection(view('connected', 'old error'))
    render(<Sidebar />)
    expect(screen.queryByText('old error')).not.toBeInTheDocument()
  })

  it('toggles read-only without recreating the connection', async () => {
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const config = JSON.parse(String(init.body))
      return new Response(JSON.stringify({ ...view('connected', null), config }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    useStudio.getState().upsertConnection(view('connected', null))
    render(<Sidebar />)
    const toggle = screen.getByRole('button', { name: 'Read-only Plant' })
    expect(toggle).toHaveAttribute('aria-pressed', 'false')

    await act(async () => fireEvent.click(toggle))
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/connections/c1')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(String(init.body))).toMatchObject({ host: 'modbus-studio-sim', read_only: true })
    expect(screen.getByRole('button', { name: 'Read-only Plant' })).toHaveAttribute('aria-pressed', 'true')
  })
})
