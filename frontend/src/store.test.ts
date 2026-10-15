import { beforeEach, describe, expect, it } from 'vitest'
import { MAX_SERIES } from './chart'
import { useStudio } from './store'
import { cell, pollData, pollView } from './test/fixtures'

const initial = useStudio.getState()

beforeEach(() => {
  localStorage.clear()
  useStudio.setState(initial, true)
})

const at = (data: ReturnType<typeof pollData>, timestamp: number) => ({ ...data, timestamp })

describe('store', () => {
  it('loads a snapshot', () => {
    const view = pollView('w1', pollData('w1', 1, [cell(0, 7)]))
    useStudio.getState().handle({ type: 'snapshot', connections: [], polls: [view] })
    const s = useStudio.getState()
    expect(Object.keys(s.polls)).toEqual(['w1'])
    expect(s.cells.w1.map((c) => c.value)).toEqual([7])
  })

  it('keeps the last good values when a read fails', () => {
    const { handle } = useStudio.getState()
    handle({ type: 'snapshot', connections: [], polls: [pollView('w1')] })
    handle({ type: 'poll', data: pollData('w1', 1, [cell(0, 1), cell(1, 2)]) })
    handle({ type: 'poll', data: pollData('w1', 2, null, 1) })
    const s = useStudio.getState()
    expect(s.cells.w1.map((c) => c.value)).toEqual([1, 2])
    expect(s.latest.w1.ok).toBe(false)
    expect(s.latest.w1.stats.errors).toBe(1)
  })

  it('ignores results for windows it does not know', () => {
    useStudio.getState().handle({ type: 'poll', data: pollData('ghost', 1, [cell(0, 1)]) })
    expect(useStudio.getState().cells.ghost).toBeUndefined()
  })

  it('drops windows that disappear from a snapshot', () => {
    const { handle } = useStudio.getState()
    handle({ type: 'snapshot', connections: [], polls: [pollView('a'), pollView('b')] })
    handle({ type: 'snapshot', connections: [], polls: [pollView('b')] })
    expect(Object.keys(useStudio.getState().polls)).toEqual(['b'])
  })

  it('records samples for plotted values, with gaps for failed reads', () => {
    const { handle, plot } = useStudio.getState()
    handle({ type: 'snapshot', connections: [], polls: [pollView('w1')] })
    handle({ type: 'poll', data: at(pollData('w1', 1, [cell(0, 5), cell(1, 6)]), 10) })
    expect(plot([{ poll: 'w1', address: 1 }])).toBe(0)
    handle({ type: 'poll', data: at(pollData('w1', 2, [cell(0, 5), cell(1, 7)]), 11) })
    handle({ type: 'poll', data: at(pollData('w1', 3, null, 1), 12) })
    // The value on screen when it was plotted comes first.
    expect(useStudio.getState().history['w1:1']).toEqual([
      { t: 10, v: 6 },
      { t: 11, v: 7 },
      { t: 12, v: null },
    ])
    expect(useStudio.getState().history['w1:0']).toBeUndefined()
    expect(JSON.parse(localStorage.getItem('modbus-studio.plotted')!)).toEqual([
      { poll: 'w1', address: 1 },
    ])
  })

  it('plots at most MAX_SERIES values and ignores duplicates', () => {
    const { plot } = useStudio.getState()
    const keys = (from: number, n: number) =>
      Array.from({ length: n }, (_, i) => ({ poll: 'w1', address: from + i }))
    expect(plot(keys(0, 3))).toBe(0)
    expect(plot(keys(0, 3))).toBe(0)
    expect(plot(keys(3, MAX_SERIES))).toBe(3)
    expect(useStudio.getState().plotted).toHaveLength(MAX_SERIES)
  })

  it('takes series off the chart when they are removed or their window goes', () => {
    const { handle, plot, unplot } = useStudio.getState()
    handle({ type: 'snapshot', connections: [], polls: [pollView('a'), pollView('b')] })
    plot([
      { poll: 'a', address: 0 },
      { poll: 'a', address: 1 },
      { poll: 'b', address: 0 },
    ])
    unplot([{ poll: 'a', address: 1 }])
    expect(useStudio.getState().history['a:1']).toBeUndefined()
    handle({ type: 'snapshot', connections: [], polls: [pollView('b')] })
    expect(useStudio.getState().plotted).toEqual([{ poll: 'b', address: 0 }])
  })
})
