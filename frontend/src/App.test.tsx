import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { useStudio } from './store'
import { cell, FakeWebSocket, pollData, pollView } from './test/fixtures'

const initial = useStudio.getState()

function mockHealth(response: Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(() => response))
}

const healthy = (auth = false) =>
  Promise.resolve(
    new Response(JSON.stringify({ status: 'ok', version: '1.2.3', auth }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )

beforeEach(() => {
  useStudio.setState(initial, true)
  FakeWebSocket.instances = []
  vi.stubGlobal('WebSocket', FakeWebSocket)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('reports an unreachable backend', async () => {
    mockHealth(Promise.reject(new TypeError('Failed to fetch')))
    render(<App />)
    expect(await screen.findByText('backend offline')).toBeInTheDocument()
  })

  it('renders windows pushed over the WebSocket', async () => {
    mockHealth(healthy())
    render(<App />)
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0]
    expect(ws.url).toMatch(/\/api\/ws$/)

    act(() =>
      ws.emit({
        type: 'snapshot',
        connections: [],
        polls: [pollView('w1', pollData('w1', 3, [cell(0, 1234)]))],
      }),
    )
    expect(await screen.findByText('1234')).toBeInTheDocument()
    expect(screen.getByText('backend v1.2.3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '+ Connection' })).toBeEnabled()
  })

  it('asks for a token and sends it as the first WebSocket message', async () => {
    mockHealth(healthy(true))
    render(<App />)
    const input = await screen.findByLabelText('Token')
    fireEvent.change(input, { target: { value: 's3cret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }))

    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    const ws = FakeWebSocket.instances[0]
    act(() => ws.onopen?.())
    expect(JSON.parse(ws.sent[0])).toEqual({ type: 'auth', token: 's3cret' })
    sessionStorage.clear()
  })
})
