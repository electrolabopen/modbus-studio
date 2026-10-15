// Filtering, timing and export for the traffic monitor. Frame headers are
// described by the backend; this module only works on those fields.
import type { TrafficEntry } from './api/types'

export interface TrafficFilter {
  /** Connection id, or '' for all. */
  connection: string
  direction: 'all' | 'tx' | 'rx'
  /** Device id / function code as typed; '' matches everything. */
  device: string
  fn: string
  /** Only exception responses and malformed frames. */
  problemsOnly: boolean
  /** Hex bytes to look for, spaces optional ("0103" finds "01 03"). */
  search: string
}

export const NO_FILTER: TrafficFilter = {
  connection: '',
  direction: 'all',
  device: '',
  fn: '',
  problemsOnly: false,
  search: '',
}

export const EXCEPTION_NAMES: Record<number, string> = {
  1: 'Illegal function',
  2: 'Illegal data address',
  3: 'Illegal data value',
  4: 'Server device failure',
  5: 'Acknowledge',
  6: 'Server device busy',
  8: 'Memory parity error',
  10: 'Gateway path unavailable',
  11: 'Gateway target device failed to respond',
}

export const isProblem = (e: TrafficEntry) => e.exception_code !== null || e.error !== null

const compactHex = (text: string) => text.replace(/[^0-9a-f]/gi, '').toUpperCase()

/** Accepts decimal or 0x-prefixed hex; null if the text is not a number. */
function parseNumber(text: string): number | null {
  const t = text.trim()
  if (!t) return null
  const n = /^0x/i.test(t) ? parseInt(t.slice(2), 16) : Number(t)
  return Number.isInteger(n) ? n : NaN
}

export function filterTraffic(entries: TrafficEntry[], f: TrafficFilter): TrafficEntry[] {
  const device = parseNumber(f.device)
  const fn = parseNumber(f.fn)
  const search = compactHex(f.search)
  return entries.filter(
    (e) =>
      (!f.connection || e.connection_id === f.connection) &&
      (f.direction === 'all' || e.direction === f.direction) &&
      (device === null || e.device_id === device) &&
      (fn === null || e.function === fn) &&
      (!f.problemsOnly || isProblem(e)) &&
      (!search || compactHex(e.hex).includes(search)),
  )
}

/**
 * Response time of each RX frame: milliseconds since the previous TX on the same
 * connection. Computed on the unfiltered list so filters do not change it.
 */
export function responseTimes(entries: TrafficEntry[]): Map<number, number> {
  const lastTx = new Map<string, number>()
  const times = new Map<number, number>()
  for (const e of entries) {
    if (e.direction === 'tx') {
      lastTx.set(e.connection_id, e.timestamp)
    } else {
      const sent = lastTx.get(e.connection_id)
      if (sent !== undefined) {
        times.set(e.seq, (e.timestamp - sent) * 1000)
        lastTx.delete(e.connection_id)
      }
    }
  }
  return times
}

export interface TrafficCounts {
  tx: number
  rx: number
  exceptions: number
  malformed: number
}

export function countTraffic(entries: TrafficEntry[]): TrafficCounts {
  const counts = { tx: 0, rx: 0, exceptions: 0, malformed: 0 }
  for (const e of entries) {
    counts[e.direction]++
    if (e.exception_code !== null) counts.exceptions++
    if (e.error !== null) counts.malformed++
  }
  return counts
}

export function describeEntry(e: TrafficEntry): string {
  if (e.error) return e.error
  if (e.exception_code !== null) {
    const code = e.exception_code.toString(16).toUpperCase().padStart(2, '0')
    return `exception ${code}h ${EXCEPTION_NAMES[e.exception_code] ?? ''}`.trim()
  }
  return ''
}

const csvField = (value: string | number | null) => {
  const text = value === null ? '' : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** CSV with one frame per line; times are ISO 8601 in UTC. */
export function trafficToCsv(
  entries: TrafficEntry[],
  connectionNames: Record<string, string>,
  times: Map<number, number>,
): string {
  const header = [
    'seq',
    'time_utc',
    'connection',
    'direction',
    'device_id',
    'function',
    'transaction_id',
    'response_ms',
    'info',
    'hex',
  ]
  const rows = entries.map((e) =>
    [
      e.seq,
      new Date(e.timestamp * 1000).toISOString(),
      connectionNames[e.connection_id] ?? e.connection_id,
      e.direction.toUpperCase(),
      e.device_id,
      e.function,
      e.transaction_id,
      times.has(e.seq) ? times.get(e.seq)!.toFixed(1) : null,
      describeEntry(e),
      e.hex,
    ]
      .map(csvField)
      .join(','),
  )
  return [header.join(','), ...rows].join('\n') + '\n'
}

/** Merge two lists of frames into one, ordered by seq, without duplicates. */
export function mergeFrames(a: TrafficEntry[], b: TrafficEntry[]): TrafficEntry[] {
  const bySeq = new Map<number, TrafficEntry>()
  for (const e of a) bySeq.set(e.seq, e)
  for (const e of b) bySeq.set(e.seq, e)
  return [...bySeq.values()].sort((x, y) => x.seq - y.seq)
}
