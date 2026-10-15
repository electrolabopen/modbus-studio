import { beforeEach, describe, expect, it } from 'vitest'
import { useStudio } from './store'
import { cell, pollData, pollView } from './test/fixtures'

const initial = useStudio.getState()

beforeEach(() => {
  useStudio.setState(initial, true)
})

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
})
