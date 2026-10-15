import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import type { Workspace } from '../api/types'
import { useStudio } from '../store'
import { cell, FakeWebSocket, pollData, pollView } from '../test/fixtures'
import { ImportWorkspaceDialog } from './ImportWorkspaceDialog'
import { PollWindow } from './PollWindow'

const initial = useStudio.getState()

type Call = { url: string; method: string; body: unknown }
let calls: Call[]

/** fetch stub: `routes` maps "METHOD /path" (no query) to [status, body]. */
function mockFetch(routes: Record<string, [number, unknown]>) {
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET'
      calls.push({ url, method, body: init.body ? JSON.parse(String(init.body)) : null })
      const [status, body] = routes[`${method} ${url.split('?')[0]}`] ?? [404, { detail: 'nope' }]
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

const workspace: Workspace = {
  version: 1,
  connections: [
    {
      type: 'tcp',
      id: 'sim',
      name: 'Simulator',
      host: 'simulator',
      port: 5020,
      timeout_s: 1,
      retries: 0,
      delay_between_requests_ms: 0,
      read_only: true,
    },
  ],
  polls: [{ ...pollView('w1').definition, connection_id: 'sim' }],
}

const jsonFile = (content: string, name = 'ws.json') =>
  new File([content], name, { type: 'application/json' })

beforeEach(() => useStudio.setState(initial, true))
afterEach(() => vi.unstubAllGlobals())

describe('workspace import', () => {
  it('summarises the file and imports in the chosen mode', async () => {
    mockFetch({ 'POST /api/workspace': [200, { connections: 1, polls: 1 }] })
    const onClose = vi.fn()
    render(<ImportWorkspaceDialog file={jsonFile(JSON.stringify(workspace))} onClose={onClose} />)
    expect(await screen.findByText(/1 connection, 1 window/)).toBeInTheDocument()
    expect(screen.getByLabelText('Workspace contents')).toHaveTextContent(
      'Simulator (read-only) · 1 window(s)',
    )
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()

    fireEvent.click(screen.getByLabelText(/Add to the current session/))
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Import' })))
    expect(calls).toEqual([
      { url: '/api/workspace?mode=merge', method: 'POST', body: workspace },
    ])
    expect(onClose).toHaveBeenCalled()
  })

  it('rejects files that are not workspaces', async () => {
    mockFetch({})
    render(<ImportWorkspaceDialog file={jsonFile('{"foo": 1}')} onClose={() => {}} />)
    expect(await screen.findByText(/Not a modbus-studio workspace/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled()
  })

  it('shows server errors such as ids in use', async () => {
    mockFetch({ 'POST /api/workspace': [409, { detail: 'already in use: sim' }] })
    render(<ImportWorkspaceDialog file={jsonFile(JSON.stringify(workspace))} onClose={() => {}} />)
    await screen.findByText(/1 connection/)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Import' })))
    expect(screen.getByRole('alert')).toHaveTextContent('already in use: sim')
  })
})

describe('workspace export', () => {
  it('downloads the workspace as JSON', async () => {
    FakeWebSocket.instances = []
    vi.stubGlobal('WebSocket', FakeWebSocket)
    mockFetch({
      'GET /api/health': [200, { status: 'ok', version: '1', auth: false }],
      'GET /api/workspace': [200, workspace],
    })
    const createObjectURL = vi.fn(() => 'blob:ws')
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }))
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<App />)
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1))
    // The link counts as open once the first message arrives.
    act(() => FakeWebSocket.instances[0].emit({ type: 'snapshot', connections: [], polls: [] }))
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Export workspace' })))

    const blob = (createObjectURL.mock.calls[0] as unknown as [Blob])[0]
    expect(JSON.parse(await blob.text())).toEqual(workspace)
    const anchor = click.mock.contexts[0] as HTMLAnchorElement
    expect(anchor.download).toMatch(/^modbus-studio-workspace-\d{8}-\d{4}\.json$/)
    click.mockRestore()
  })
})

describe('CSV register map import', () => {
  function renderWindow() {
    const view = pollView('w1')
    const { handle } = useStudio.getState()
    handle({ type: 'snapshot', connections: [], polls: [view] })
    handle({ type: 'poll', data: pollData('w1', 1, [cell(0, 1)]) })
    render(<PollWindow view={view} />)
  }

  const pick = (content: string) =>
    fireEvent.change(screen.getByLabelText('CSV register map file'), {
      target: { files: [new File([content], 'map.csv', { type: 'text/csv' })] },
    })

  it('confirms and applies the file', async () => {
    mockFetch({ 'POST /api/polls/w1/register-map': [200, pollView('w1')] })
    renderWindow()
    const csv = '# comment\naddress,alias,type\n0,counter,uint16\n1,x,int16\n'
    pick(csv)
    expect(await screen.findByText(/· 2 rows/)).toBeInTheDocument()
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Apply' })))
    expect(calls).toEqual([
      { url: '/api/polls/w1/register-map', method: 'POST', body: { csv } },
    ])
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('lists the problems by line and applies nothing', async () => {
    const errors = [
      { line: 3, message: 'unknown type float16' },
      { line: 5, message: 'address 9-10 is outside this window (0-2)' },
    ]
    mockFetch({ 'POST /api/polls/w1/register-map': [400, { detail: '2 problem(s)', errors }] })
    renderWindow()
    pick('address,type\n0,int16\n1,float16\n')
    await screen.findByText(/· 2 rows/)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Apply' })))
    const list = screen.getByLabelText('CSV problems')
    expect(list).toHaveTextContent('line 3: unknown type float16')
    expect(list).toHaveTextContent('line 5: address 9-10 is outside this window (0-2)')
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled()
  })

  it('offers to grow a window that is too small for the file', async () => {
    const errors = [{ line: 3, message: 'address 5 is outside this window (0-2)' }]
    const grown = pollView('w1')
    grown.definition.quantity = 6
    const fetchMock = vi.fn(async (url: string) =>
      url.endsWith('?fit=true')
        ? new Response(JSON.stringify(grown), { status: 200 })
        : new Response(
            JSON.stringify({ detail: '1 problem(s)', errors, fit: { address: 0, quantity: 6 } }),
            { status: 400 },
          ),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderWindow()
    pick('address,type\n0,int16\n5,int16\n')
    await screen.findByText(/· 2 rows/)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Apply' })))
    expect(screen.getByRole('status')).toHaveTextContent('addresses 0–5 (6 registers)')
    expect(screen.getByLabelText('CSV problems')).toHaveTextContent('line 3: address 5 is outside')

    await act(async () =>
      fireEvent.click(screen.getByRole('button', { name: 'Grow window and apply' })),
    )
    expect(fetchMock).toHaveBeenLastCalledWith(
      '/api/polls/w1/register-map?fit=true',
      expect.objectContaining({ method: 'POST' }),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(useStudio.getState().polls.w1.definition.quantity).toBe(6)
  })
})
