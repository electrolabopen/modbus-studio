import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ConnectionView, WritePlan } from '../api/types'
import { useStudio } from '../store'
import { cell, pollData, pollView } from '../test/fixtures'
import { PollWindow } from './PollWindow'

const initial = useStudio.getState()

const connection = (read_only: boolean): ConnectionView => ({
  config: {
    type: 'tcp',
    id: 'c1',
    name: 'Plant',
    host: 'simulator',
    port: 5020,
    timeout_s: 1,
    retries: 0,
    delay_between_requests_ms: 0,
    read_only,
  },
  state: 'connected',
  stats: {},
})

const plan = (over: Partial<WritePlan> = {}): WritePlan => ({
  poll_id: 'w1',
  connection_id: 'c1',
  device_id: 1,
  function: 6,
  address: 2,
  values: [234],
  requested: 23.45,
  result: 23.4,
  text: '23.4',
  rounded: true,
  unit: '°C',
  dtype: 'int16',
  order: 'ABCD',
  scale: 0.1,
  ...over,
})

type Call = { url: string; body: unknown }
let calls: Call[]

function mockApi(respond: (url: string, body: unknown) => unknown) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      const body = init.body ? JSON.parse(String(init.body)) : null
      calls.push({ url, body })
      return new Response(JSON.stringify(respond(url, body)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

function renderWindow(readOnly = false) {
  const view = pollView('w1')
  const { handle } = useStudio.getState()
  handle({ type: 'snapshot', connections: [connection(readOnly)], polls: [view] })
  handle({
    type: 'poll',
    data: pollData('w1', 1, [cell(0, 7), cell(1, 8), cell(2, 21.5, { text: '21.5', unit: '°C' })]),
  })
  render(<PollWindow view={view} />)
}

beforeEach(() => useStudio.setState(initial, true))
afterEach(() => vi.unstubAllGlobals())

describe('write by double-click', () => {
  it('previews the raw registers and writes after confirmation', async () => {
    mockApi(() => plan())
    renderWindow()
    fireEvent.doubleClick(screen.getByText('21.5'))

    const input = screen.getByLabelText('Value (°C)')
    expect(input).toHaveValue('21.5')
    fireEvent.change(input, { target: { value: '23.45' } })

    const preview = await screen.findByLabelText('Write preview')
    expect(preview).toHaveTextContent('06 Write Single Register')
    expect(preview).toHaveTextContent('int16 · ABCD · scale 0.1')
    expect(screen.getByTestId('write-raw')).toHaveTextContent('0x00EA (234)')
    expect(screen.getByRole('status')).toHaveTextContent('the device will hold 23.4 °C')
    const last = calls.at(-1)!
    expect(last.url).toBe('/api/polls/w1/write/preview')
    expect(last.body).toEqual({ address: 2, value: 23.45, force_multiple: false })

    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Write' })))
    expect(calls.at(-1)).toEqual({
      url: '/api/polls/w1/write',
      body: { address: 2, value: 23.45, force_multiple: false },
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('focuses Cancel when it opens, so Enter does not write', () => {
    mockApi(() => plan())
    renderWindow()
    fireEvent.doubleClick(screen.getByText('21.5'))
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
  })

  it('cannot confirm an invalid value', async () => {
    mockApi(() => plan())
    renderWindow()
    fireEvent.doubleClick(screen.getByText('7'))
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: 'abc' } })
    expect(screen.getByText(/Enter a number/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Write' })).toBeDisabled()
  })

  it('accepts hex input', async () => {
    mockApi(() => plan({ values: [31], text: '31', rounded: false, scale: 1 }))
    renderWindow()
    fireEvent.doubleClick(screen.getByText('7'))
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: '0x1F' } })
    await waitFor(() => expect(calls.at(-1)?.body).toEqual({ address: 0, value: 31, force_multiple: false }))
  })

  it('does not open on a read-only connection', () => {
    mockApi(() => plan())
    renderWindow(true)
    expect(screen.getByText('read-only')).toBeInTheDocument()
    fireEvent.doubleClick(screen.getByText('7'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByText(/Connection "Plant" is read-only/)).toBeInTheDocument()
    expect(calls).toEqual([])
  })
})
