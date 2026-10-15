import { describe, expect, it } from 'vitest'
import {
  MAX_AGE_S,
  alignSeries,
  alignedToCsv,
  appendSample,
  cellNumber,
  formatNumber,
  sampleOf,
  valuesAt,
  type Aligned,
  type Sample,
} from './chart'
import { cell, pollData } from './test/fixtures'

const samples = (...pairs: [number, number | null][]): Sample[] =>
  pairs.map(([t, v]) => ({ t, v }))

describe('cellNumber', () => {
  it('plots numbers, coils as 0/1 and everything else as a gap', () => {
    expect(cellNumber(cell(0, 12.5))).toBe(12.5)
    expect(cellNumber(cell(0, 0, { value: true }))).toBe(1)
    expect(cellNumber(cell(0, 0, { value: false }))).toBe(0)
    expect(cellNumber(cell(0, 0, { value: null }))).toBeNull()
    expect(cellNumber(cell(0, 0, { value: NaN }))).toBeNull()
    expect(cellNumber(cell(0, 1, { error: 'bad' }))).toBeNull()
    expect(cellNumber(cell(1, 1, { covered_by: 0 }))).toBeNull()
    expect(cellNumber(undefined)).toBeNull()
  })
})

describe('sampleOf', () => {
  it('takes the cell at the address, and a failed read as a gap', () => {
    const ok = { ...pollData('w1', 1, [cell(0, 3), cell(1, 4)]), timestamp: 50 }
    expect(sampleOf(ok, 1)).toEqual({ t: 50, v: 4 })
    expect(sampleOf(ok, 9)).toEqual({ t: 50, v: null })
    const failed = { ...pollData('w1', 2, null, 1), timestamp: 51 }
    expect(sampleOf(failed, 1)).toEqual({ t: 51, v: null })
  })
})

describe('appendSample', () => {
  it('drops samples older than MAX_AGE_S once there is some slack', () => {
    const buffer: Sample[] = []
    for (let t = 0; t <= MAX_AGE_S + 120; t += 10) appendSample(buffer, { t, v: t })
    // Up to a minute of slack beyond MAX_AGE_S, never more.
    expect(buffer[0].t).toBeGreaterThan(0)
    expect(buffer[0].t).toBeGreaterThanOrEqual(120 - 60)
    expect(buffer[buffer.length - 1].t).toBe(MAX_AGE_S + 120)
  })

  it('starts over when the clock goes back', () => {
    const buffer = samples([100, 1], [101, 2])
    appendSample(buffer, { t: 50, v: 3 })
    expect(buffer).toEqual(samples([50, 3]))
  })
})

describe('alignSeries', () => {
  it('merges onto one time axis: undefined where another series sampled, null for gaps', () => {
    const a = samples([1, 10], [3, null], [5, 30])
    const b = samples([2, 1], [3, 2])
    expect(alignSeries([a, b])).toEqual([
      [1, 2, 3, 5],
      [10, undefined, null, 30],
      [undefined, 1, 2, undefined],
    ])
  })

  it('keeps one sample before the start so lines enter from the edge', () => {
    const a = samples([1, 1], [2, 2], [3, 3], [4, 4])
    expect(alignSeries([a], 2.5)).toEqual([
      [2, 3, 4],
      [2, 3, 4],
    ])
    expect(alignSeries([[]], 0)).toEqual([[], []])
  })
})

describe('valuesAt', () => {
  const data: Aligned = [
    [1, 2, 3],
    [5, undefined, undefined],
    [1, 2, null],
    [undefined, undefined, undefined],
  ]

  it('takes the latest sample of each series, reporting a final gap', () => {
    expect(valuesAt(data)).toEqual([5, null, null])
  })

  it('looks back from a row where a series did not sample', () => {
    expect(valuesAt(data, 1)).toEqual([5, 2, null])
    expect(valuesAt(data, 0)).toEqual([5, 1, null])
  })
})

describe('formatNumber', () => {
  it('keeps integers and rounds to 6 significant digits', () => {
    expect(formatNumber(42)).toBe('42')
    expect(formatNumber(99.99999999)).toBe('100')
    expect(formatNumber(0.1 + 0.2)).toBe('0.3')
    expect(formatNumber(-12.345678)).toBe('-12.3457')
  })
})

describe('alignedToCsv', () => {
  it('writes ISO and Unix time and one column per series from the start', () => {
    const csv = alignedToCsv(
      ['level (m)', 'pump, "main"'],
      [
        [0, 1, 2.5],
        [1, null, 3],
        [undefined, 7, undefined],
      ],
      1,
    )
    expect(csv).toBe(
      [
        'time,unix_s,level (m),"pump, ""main"""',
        '1970-01-01T00:00:01.000Z,1.000,,7',
        '1970-01-01T00:00:02.500Z,2.500,3,',
        '',
      ].join('\n'),
    )
  })
})
