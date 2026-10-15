import { describe, expect, it } from 'vitest'
import type { TrafficEntry } from './api/types'
import { frame } from './test/fixtures'
import {
  NO_FILTER,
  countTraffic,
  filterTraffic,
  mergeFrames,
  responseTimes,
  trafficToCsv,
} from './traffic'

const frames = [
  frame(1),
  frame(2),
  frame(3, { connection_id: 'c2', device_id: 7, function: 6, hex: '07 06 00 01 00 05 D8 6A' }),
  frame(4, { connection_id: 'c2', device_id: 7, function: 6, exception_code: 2 }),
  frame(5, { error: 'bad CRC 0000, expected CDC5' }),
]

const seqs = (list: TrafficEntry[]) => list.map((e) => e.seq)

describe('filterTraffic', () => {
  it('filters by connection, direction, device, function and problems', () => {
    expect(seqs(filterTraffic(frames, NO_FILTER))).toEqual([1, 2, 3, 4, 5])
    expect(seqs(filterTraffic(frames, { ...NO_FILTER, connection: 'c2' }))).toEqual([3, 4])
    expect(seqs(filterTraffic(frames, { ...NO_FILTER, direction: 'rx' }))).toEqual([2, 4])
    expect(seqs(filterTraffic(frames, { ...NO_FILTER, device: '7' }))).toEqual([3, 4])
    expect(seqs(filterTraffic(frames, { ...NO_FILTER, fn: '0x06' }))).toEqual([3, 4])
    expect(seqs(filterTraffic(frames, { ...NO_FILTER, problemsOnly: true }))).toEqual([4, 5])
  })

  it('searches hex with or without spaces, and ignores invalid numbers', () => {
    expect(seqs(filterTraffic(frames, { ...NO_FILTER, search: 'd86a' }))).toEqual([3])
    expect(seqs(filterTraffic(frames, { ...NO_FILTER, search: '06 00 01' }))).toEqual([3])
    // "abc" is not a device id: nothing matches rather than everything.
    expect(filterTraffic(frames, { ...NO_FILTER, device: 'abc' })).toEqual([])
  })
})

describe('responseTimes', () => {
  it('measures each RX from the previous TX of its connection', () => {
    const times = responseTimes([
      frame(1, { timestamp: 10.0, direction: 'tx' }),
      frame(2, { timestamp: 10.1, direction: 'tx', connection_id: 'c2' }),
      frame(3, { timestamp: 10.012, direction: 'rx' }),
      frame(4, { timestamp: 10.15, direction: 'rx', connection_id: 'c2' }),
      frame(5, { timestamp: 10.2, direction: 'rx' }), // no TX before it
    ])
    expect(times.get(3)).toBeCloseTo(12, 6)
    expect(times.get(4)).toBeCloseTo(50, 6)
    expect(times.has(5)).toBe(false)
  })
})

describe('countTraffic', () => {
  it('counts directions, exceptions and malformed frames', () => {
    expect(countTraffic(frames)).toEqual({ tx: 3, rx: 2, exceptions: 1, malformed: 1 })
  })
})

describe('trafficToCsv', () => {
  it('writes one line per frame with quoted fields when needed', () => {
    const csv = trafficToCsv(
      [frame(1, { timestamp: 0 }), frame(2, { timestamp: 0.012, exception_code: 2 })],
      { c1: 'Plant, line 1' },
      new Map([[2, 12]]),
    )
    expect(csv.split('\n')).toEqual([
      'seq,time_utc,connection,direction,device_id,function,transaction_id,response_ms,info,hex',
      '1,1970-01-01T00:00:00.000Z,"Plant, line 1",TX,1,3,1,,,00 01 00 00 00 06 01 03 00 00 00 0A',
      '2,1970-01-01T00:00:00.012Z,"Plant, line 1",RX,1,3,1,12.0,exception 02h Illegal data address,00 01 00 00 00 06 01 03 00 00 00 0A',
      '',
    ])
  })
})

describe('mergeFrames', () => {
  it('orders by seq and drops duplicates', () => {
    expect(seqs(mergeFrames([frame(3), frame(1)], [frame(2), frame(3)]))).toEqual([1, 2, 3])
  })
})
