import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SerialPort } from '../api/types'
import { useStudio } from '../store'
import { ConnectionDialog } from './ConnectionDialog'

const initial = useStudio.getState()

const ports: SerialPort[] = [
  {
    device: '/dev/ttyUSB0',
    description: 'FT232R USB UART',
    manufacturer: 'FTDI',
    serial_number: 'A50285BI',
    vid: 0x0403,
    pid: 0x6001,
    stable_path: '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0',
    used_by: [],
  },
  {
    device: '/dev/ttyS0',
    description: '',
    manufacturer: null,
    serial_number: null,
    vid: null,
    pid: null,
    stable_path: null,
    used_by: ['line1'],
  },
]

function mockServer() {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    if (url === '/api/serial-ports') return new Response(JSON.stringify(ports))
    const config = JSON.parse(String(init.body))
    return new Response(
      JSON.stringify({ config: { ...config, id: 'new' }, state: 'connecting', stats: {} }),
      { status: 201 },
    )
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

beforeEach(() => useStudio.setState(initial, true))
afterEach(() => vi.unstubAllGlobals())

describe('ConnectionDialog', () => {
  it('creates an RTU connection on a port picked from the list', async () => {
    const fetchMock = mockServer()
    const onClose = vi.fn()
    render(<ConnectionDialog onClose={onClose} />)
    fireEvent.change(screen.getByLabelText('Mode'), { target: { value: 'rtu' } })

    // The USB adapter is offered under its stable /dev/serial/by-id name.
    const usb = await screen.findByRole('button', { name: /ttyUSB0/ })
    expect(usb).toHaveTextContent('FTDI · VID:PID 0403:6001 · S/N A50285BI')
    expect(screen.getByRole('button', { name: /ttyS0/ })).toHaveTextContent('used by line1')
    fireEvent.click(usb)
    expect(screen.getByLabelText('Serial port')).toHaveValue(ports[0].stable_path)

    fireEvent.change(screen.getByLabelText('Baud rate'), { target: { value: '9600' } })
    fireEvent.change(screen.getByLabelText('Parity'), { target: { value: 'N' } })
    fireEvent.change(screen.getByLabelText('Stop bits'), { target: { value: '2' } })
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Create' })))

    const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/connections')!
    expect(JSON.parse(String(init!.body))).toEqual({
      type: 'rtu',
      name: '',
      serial_port: ports[0].stable_path,
      baudrate: 9600,
      bytesize: 8,
      parity: 'N',
      stopbits: 2,
      timeout_s: 1,
      retries: 0,
      delay_between_requests_ms: 0,
      read_only: false,
    })
    expect(useStudio.getState().connections.new.config.type).toBe('rtu')
    expect(onClose).toHaveBeenCalled()
  })

  it('does not look for serial ports for TCP connections', () => {
    const fetchMock = mockServer()
    render(<ConnectionDialog onClose={() => {}} />)
    expect(screen.getByLabelText('IP address / host')).toHaveValue('127.0.0.1')
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
