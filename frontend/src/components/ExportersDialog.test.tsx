import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExporterStatus, ExportersView } from '../api/types'
import { exportersSummary } from '../exporters'
import { useStudio } from '../store'
import { ExportersDialog } from './ExportersDialog'

const initial = useStudio.getState()

const status = (overrides: Partial<ExporterStatus> = {}): ExporterStatus => ({
  state: 'ok',
  last_error: null,
  last_error_at: null,
  last_success_at: null,
  points_sent: 1234,
  writes: 7,
  errors: 0,
  dropped: 0,
  pending: 3,
  connected: null,
  ...overrides,
})

function exporters(): ExportersView {
  return {
    influxdb: {
      config: {
        enabled: true,
        url: 'http://influxdb:8086',
        org: 'plant',
        bucket: 'modbus',
        token_set: true,
        aliased_only: false,
        flush_interval_ms: 1000,
        batch_size: 5000,
        buffer_size: 100000,
        timeout_s: 5,
        verify_tls: true,
      },
      status: status(),
    },
    mqtt: {
      config: {
        enabled: false,
        host: 'localhost',
        port: 1883,
        client_id: '',
        username: '',
        password_set: false,
        topic: 'modbus-studio/{connection}/{device}/{alias}',
        qos: 0,
        retain: false,
        aliased_only: false,
        keepalive_s: 60,
        buffer_size: 10000,
        tls: false,
        ca_file: '',
        cert_file: '',
        key_file: '',
        verify_tls: true,
      },
      status: status({
        state: 'error',
        connected: false,
        points_sent: 0,
        last_error: 'cannot connect to localhost:1883: connection refused',
        last_error_at: 1_800_000_000,
      }),
    },
  }
}

interface Call {
  url: string
  method: string
  body: Record<string, unknown> | null
}

function mockServer(respond?: (call: Call) => Response | undefined) {
  const calls: Call[] = []
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const call = {
      url,
      method: init.method ?? 'GET',
      body: init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null,
    }
    calls.push(call)
    const custom = respond?.(call)
    if (custom) return custom
    const view = exporters()
    if (url === '/api/exporters') return new Response(JSON.stringify(view))
    if (url === '/api/exporters/influxdb' && call.method === 'PUT') {
      const { token, ...config } = call.body ?? {}
      return new Response(
        JSON.stringify({
          config: { ...config, token_set: token === null || !!token },
          status: view.influxdb.status,
        }),
      )
    }
    if (url.endsWith('/test')) {
      return new Response(JSON.stringify({ ok: true, message: 'it works', elapsed_ms: 12.3 }))
    }
    return new Response('{}', { status: 404 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

beforeEach(() => useStudio.setState(initial, true))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

const tokenField = () => screen.getByLabelText('Token') as HTMLInputElement

describe('ExportersDialog', () => {
  it('shows the settings and the live status, but never the token', async () => {
    mockServer()
    render(<ExportersDialog onClose={() => {}} />)
    expect(await screen.findByDisplayValue('http://influxdb:8086')).toBeInTheDocument()
    expect(screen.getByText('Writing')).toBeInTheDocument()
    expect(screen.getByText('1,234')).toBeInTheDocument() // points sent
    expect(tokenField().type).toBe('password')
    expect(tokenField().value).toBe('')
    expect(tokenField().placeholder).toMatch(/saved \(hidden\)/)
    expect(screen.getByLabelText('Remove the saved token')).not.toBeChecked()
  })

  it('keeps the saved token unless a new one is typed, and forgets it after saving', async () => {
    const calls = mockServer()
    render(<ExportersDialog onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText('Bucket'), { target: { value: 'other' } })
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByText('Saved and applied.')
    let put = calls.filter((c) => c.method === 'PUT').at(-1)
    expect(put?.body).toMatchObject({ bucket: 'other', token: null })

    fireEvent.change(tokenField(), { target: { value: 's3cret' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByText('Saved and applied.')
    put = calls.filter((c) => c.method === 'PUT').at(-1)
    expect(put?.body).toMatchObject({ token: 's3cret' })
    expect(tokenField().value).toBe('') // typed, sent, then gone from the page
    expect(document.body.innerHTML).not.toContain('s3cret')
  })

  it('removes the saved token on request', async () => {
    const calls = mockServer()
    render(<ExportersDialog onClose={() => {}} />)
    fireEvent.click(await screen.findByLabelText('Remove the saved token'))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    await screen.findByText('Saved and applied.')
    expect(calls.find((c) => c.method === 'PUT')?.body).toMatchObject({ token: '' })
  })

  it('tests the settings in the form without saving them', async () => {
    const calls = mockServer()
    render(<ExportersDialog onClose={() => {}} />)
    fireEvent.change(await screen.findByLabelText('Organization'), { target: { value: 'o2' } })
    fireEvent.change(tokenField(), { target: { value: 'try-me' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByRole('status')).toHaveTextContent('✓ it works (12 ms)')
    const test = calls.find((c) => c.url === '/api/exporters/influxdb/test')
    expect(test?.body).toMatchObject({ org: 'o2', token: 'try-me' })
    expect(calls.some((c) => c.method === 'PUT')).toBe(false)

    // The result described the form as it was: editing it clears the result.
    fireEvent.change(screen.getByLabelText('Organization'), { target: { value: 'o3' } })
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('edits and tests MQTT on its own tab', async () => {
    const calls = mockServer((call) =>
      call.url === '/api/exporters/mqtt/test'
        ? new Response(
            JSON.stringify({
              ok: false,
              message: 'connection refused by the broker: Not authorized',
              elapsed_ms: 5,
            }),
          )
        : undefined,
    )
    render(<ExportersDialog onClose={() => {}} />)
    fireEvent.click(await screen.findByRole('tab', { name: 'MQTT' }))
    expect(screen.getByText('Not connected')).toBeInTheDocument()
    expect(screen.getByText(/cannot connect to localhost:1883/)).toBeInTheDocument()
    const password = screen.getByLabelText('Password') as HTMLInputElement
    expect(password.type).toBe('password')
    expect(screen.queryByLabelText('Remove the saved password')).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'plant/{window}' } })
    expect(screen.getByText('plant/Window')).toBeInTheDocument() // the example topic
    fireEvent.click(screen.getByLabelText(/^TLS/))
    expect(screen.getByLabelText(/CA certificate/)).toBeInTheDocument()
    fireEvent.change(password, { target: { value: 'pw' } })
    fireEvent.click(screen.getByRole('button', { name: 'Test connection' }))
    expect(await screen.findByRole('status')).toHaveTextContent('✗ connection refused')
    expect(calls.find((c) => c.url === '/api/exporters/mqtt/test')?.body).toMatchObject({
      topic: 'plant/{window}',
      tls: true,
      password: 'pw',
    })
  })

  it('shows validation errors from the server', async () => {
    mockServer((call) =>
      call.method === 'PUT'
        ? new Response(
            JSON.stringify({
              detail: [
                { loc: ['body', 'topic'], msg: 'Value error, unknown placeholder {name} in topic' },
              ],
            }),
            { status: 422 },
          )
        : undefined,
    )
    render(<ExportersDialog onClose={() => {}} initialTab="mqtt" />)
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'topic: unknown placeholder {name} in topic',
    )
  })

  it('refreshes the status while open', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const calls = mockServer()
    render(<ExportersDialog onClose={() => {}} />)
    await screen.findByText('Writing')
    const before = calls.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100)
    })
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(before + 2))
  })
})

describe('exportersSummary', () => {
  it('names the state of each exporter', () => {
    expect(exportersSummary(exporters())).toBe('InfluxDB: Writing · MQTT: Not connected')
    expect(exportersSummary(null)).toBe('InfluxDB and MQTT exporters')
  })
})
