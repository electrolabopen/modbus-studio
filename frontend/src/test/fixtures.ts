import type { Cell, PollData, PollStats, PollView, TrafficEntry } from '../api/types'
import { DEFAULT_FORMAT } from '../api/types'

export const stats = (polls: number, errors = 0): PollStats => ({
  polls,
  valid: polls - errors,
  timeouts: errors,
  exceptions: 0,
  invalid: 0,
  disconnected: 0,
  errors,
})

export const cell = (address: number, value: number, extra: Partial<Cell> = {}): Cell => ({
  address,
  value,
  text: String(value),
  raw: [value],
  alias: '',
  unit: '',
  covered_by: null,
  error: null,
  ...extra,
})

export const pollView = (id = 'w1', data: PollData | null = null): PollView => ({
  definition: {
    id,
    connection_id: 'c1',
    name: 'Tank',
    device_id: 1,
    function: 3,
    address: 0,
    quantity: 3,
    scan_rate_ms: 1000,
    enabled: true,
    default_format: DEFAULT_FORMAT,
    formats: {},
  },
  running: true,
  stats: data?.stats ?? stats(0),
  data,
})

export const pollData = (
  id: string,
  seq: number,
  cells: Cell[] | null,
  errors = 0,
): PollData => ({
  poll_id: id,
  seq,
  timestamp: 0,
  duration_ms: 1,
  ok: cells !== null,
  error_kind: cells === null ? 'timeout' : null,
  error: cells === null ? 'no response (timeout)' : null,
  exception_code: null,
  stats: stats(seq, errors),
  cells: cells ?? [],
})

/** Minimal WebSocket stand-in that never connects. */
export class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: ((e: { code: number }) => void) | null = null
  sent: string[] = []
  readonly url: string

  constructor(url: string) {
    this.url = url
    FakeWebSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  close() {}

  /** Deliver a server message to the app. */
  emit(message: unknown) {
    this.onmessage?.({ data: JSON.stringify(message) })
  }
}

/** A captured frame; odd seq numbers are TX, even ones RX. */
export const frame = (seq: number, over: Partial<TrafficEntry> = {}): TrafficEntry => ({
  seq,
  timestamp: 1000 + seq / 100,
  connection_id: 'c1',
  direction: seq % 2 ? 'tx' : 'rx',
  hex: '00 01 00 00 00 06 01 03 00 00 00 0A',
  device_id: 1,
  function: 3,
  exception_code: null,
  transaction_id: 1,
  error: null,
  ...over,
})
