import type { Cell, PollData } from './api/types'

/** One plotted value: the cell at ``address`` of polling window ``poll``. */
export interface SeriesKey {
  poll: string
  address: number
}

/** A sample; ``v`` is null when the read failed or the cell has no number. */
export interface Sample {
  /** Unix time in seconds. */
  t: number
  v: number | null
}

/** Most series on the chart at once; beyond this it stops being readable. */
export const MAX_SERIES = 8
/** History kept per series, whatever the time span shown. */
export const MAX_AGE_S = 3600
/** Hard cap per series: an hour at 100 ms is 36 000 samples. */
export const MAX_SAMPLES = 40_000

export const SPANS: { seconds: number; label: string }[] = [
  { seconds: 30, label: '30 s' },
  { seconds: 60, label: '1 min' },
  { seconds: 300, label: '5 min' },
  { seconds: 900, label: '15 min' },
  { seconds: 3600, label: '1 h' },
]

/** Distinct on the dark background and from each other; assigned in order. */
export const COLORS = [
  '#6cb6ff',
  '#3ecf8e',
  '#e5b454',
  '#ef6b6b',
  '#c58af9',
  '#4dd0e1',
  '#ff9e64',
  '#a3be8c',
]

export const seriesId = (k: SeriesKey) => `${k.poll}:${k.address}`

export const sameSeries = (a: SeriesKey, b: SeriesKey) =>
  a.poll === b.poll && a.address === b.address

/** Numeric value of a cell: coils plot as 0/1, unreadable cells as a gap. */
export function cellNumber(cell: Cell | undefined): number | null {
  if (!cell || cell.error !== null || cell.covered_by !== null) return null
  if (typeof cell.value === 'boolean') return cell.value ? 1 : 0
  return typeof cell.value === 'number' && Number.isFinite(cell.value) ? cell.value : null
}

/** The sample a poll result gives for ``address``; a failed read is a gap. */
export function sampleOf(data: PollData, address: number): Sample {
  const v = data.ok ? cellNumber(data.cells.find((c) => c.address === address)) : null
  return { t: data.timestamp, v }
}

/**
 * Append in place and drop what is too old. Trimming waits until there is a
 * little slack so that appending stays cheap.
 */
export function appendSample(buffer: Sample[], sample: Sample): void {
  const last = buffer[buffer.length - 1]
  if (last && sample.t < last.t) buffer.length = 0 // clock went back: start over
  buffer.push(sample)
  const oldest = sample.t - MAX_AGE_S
  if (buffer.length > MAX_SAMPLES * 1.1 || buffer[0].t < oldest - 60) {
    let drop = Math.max(0, buffer.length - MAX_SAMPLES)
    while (drop < buffer.length && buffer[drop].t < oldest) drop++
    buffer.splice(0, drop)
  }
}

/** Index of the first sample at or after ``t`` (binary search). */
function firstAtOrAfter(buffer: Sample[], t: number): number {
  let lo = 0
  let hi = buffer.length
  while (lo < hi) {
    const mid = (lo + hi) >> 1
    if (buffer[mid].t < t) lo = mid + 1
    else hi = mid
  }
  return lo
}

/** uPlot's aligned data: a shared time axis, then one value array per series. */
export type Aligned = [number[], ...(number | null | undefined)[][]]

/**
 * Merge per-series samples onto one sorted time axis. Windows poll at
 * different instants, so a series has ``undefined`` where another one sampled
 * (uPlot draws across it) and ``null`` where a read failed (uPlot breaks the
 * line). One sample before ``from`` is kept so lines enter from the left edge.
 */
export function alignSeries(buffers: Sample[][], from = -Infinity): Aligned {
  const pos = buffers.map((b) => Math.max(0, firstAtOrAfter(b, from) - 1))
  const times: number[] = []
  const columns: (number | null | undefined)[][] = buffers.map(() => [])
  for (;;) {
    let t = Infinity
    buffers.forEach((b, i) => {
      if (pos[i] < b.length && b[pos[i]].t < t) t = b[pos[i]].t
    })
    if (t === Infinity) break
    times.push(t)
    buffers.forEach((b, i) => {
      if (pos[i] < b.length && b[pos[i]].t === t) columns[i].push(b[pos[i]++].v)
      else columns[i].push(undefined)
    })
  }
  return [times, ...columns]
}

/**
 * Value of each series at row ``index`` of ``data`` (default: the last row):
 * its latest sample at or before that time, since windows sample at different
 * instants. Null when it has none yet, or that read failed.
 */
export function valuesAt(data: Aligned, index = data[0].length - 1): (number | null)[] {
  return data.slice(1).map((column) => {
    for (let i = Math.min(index, column.length - 1); i >= 0; i--)
      if (column[i] !== undefined) return column[i]!
    return null
  })
}

/** Up to 6 significant digits, without trailing zeros. */
export const formatNumber = (v: number) =>
  Number.isInteger(v) ? String(v) : String(Number(v.toPrecision(6)))

const csvField = (s: string) => (/[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s)

/** Aligned samples as CSV: ISO time, Unix time, one column per series; rows from ``from``. */
export function alignedToCsv(labels: string[], data: Aligned, from = -Infinity): string {
  const [times, ...columns] = data
  const lines = [['time', 'unix_s', ...labels].map(csvField).join(',')]
  times.forEach((t, i) => {
    if (t < from) return
    const values = columns.map((c) => (c[i] === null || c[i] === undefined ? '' : String(c[i])))
    lines.push([new Date(t * 1000).toISOString(), t.toFixed(3), ...values].join(','))
  })
  return lines.join('\n') + '\n'
}
