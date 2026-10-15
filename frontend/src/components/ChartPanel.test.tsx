import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PollData } from '../api/types'
import { useStudio } from '../store'
import { cell, pollData, pollView } from '../test/fixtures'
import { downloadText } from '../util'
import { ChartPanel } from './ChartPanel'

// jsdom has no canvas: record what the panel asks of uPlot instead.
const plots = vi.hoisted(() => [] as FakePlot[])
interface FakePlot {
  opts: { series: { label?: string; paths?: unknown; show?: boolean }[] }
  data: unknown[][]
  setDataCalls: number
  destroyed: boolean
  shown: Record<number, boolean>
}

vi.mock('uplot', () => {
  class Plot {
    cursor = { idx: null }
    select = { width: 0 }
    setDataCalls = 0
    destroyed = false
    shown: Record<number, boolean> = {}
    opts: FakePlot['opts']
    data: unknown[][]
    constructor(opts: FakePlot['opts'], data: unknown[][]) {
      this.opts = opts
      this.data = data
      plots.push(this)
    }
    batch(fn: () => void) {
      fn()
    }
    setData(data: unknown[][]) {
      this.data = data
      this.setDataCalls++
    }
    setScale() {}
    setSize() {}
    setSeries(i: number, { show }: { show: boolean }) {
      this.shown[i] = show
    }
    destroy() {
      this.destroyed = true
    }
    static paths = { stepped: () => 'stepped' }
  }
  return { default: Plot }
})

vi.mock('../util', async (original) => ({
  ...(await original<typeof import('../util')>()),
  downloadText: vi.fn(),
}))

const initial = useStudio.getState()
const t0 = Date.now() / 1000 - 5

// Cell w1:1 has the unit "m" set in the window's formats, as the server reports it.
const poll = (id: string, seq: number, values: (number | boolean)[] | null): PollData => ({
  ...pollData(
    id,
    seq,
    values &&
      values.map((v, i) =>
        cell(i, 0, { value: v, text: String(v), unit: id === 'w1' && i === 1 ? 'm' : '' }),
      ),
  ),
  timestamp: t0 + seq,
})
const deliver = (data: PollData) => act(() => useStudio.getState().handle({ type: 'poll', data }))
const lastPlot = () => plots[plots.length - 1]

beforeEach(() => {
  localStorage.clear()
  plots.length = 0
  useStudio.setState(initial, true)
  const tank = pollView('w1')
  tank.definition.formats = { 1: { ...tank.definition.default_format, alias: 'level', unit: 'm' } }
  const coils = pollView('w2')
  coils.definition.name = 'Pumps'
  coils.definition.function = 1
  useStudio.getState().handle({ type: 'snapshot', connections: [], polls: [tank, coils] })
})

describe('ChartPanel', () => {
  it('explains how to add values when nothing is plotted', () => {
    render(<ChartPanel onClose={() => {}} />)
    expect(screen.getByText(/press/)).toHaveTextContent('Select rows in a polling window')
    expect(plots).toHaveLength(0)
  })

  it('plots live values with a legend of the latest ones', () => {
    deliver(poll('w1', 1, [10, 20]))
    useStudio.getState().plot([
      { poll: 'w1', address: 1 },
      { poll: 'w2', address: 0 },
    ])
    render(<ChartPanel onClose={() => {}} />)

    const legend = screen.getByRole('list', { name: 'Series' })
    expect(within(legend).getByText('level').closest('button')).toHaveAttribute(
      'title',
      'Tank @ 1 · click to hide',
    )
    expect(within(legend).getByText('Pumps @ 0')).toBeInTheDocument()
    expect(screen.getByTestId('chart-value-w1:1')).toHaveTextContent('20 m')
    expect(screen.getByTestId('chart-value-w2:0')).toHaveTextContent('—')
    // Coils are drawn as steps.
    expect(lastPlot().opts.series.map((s) => s.paths)).toEqual([undefined, undefined, 'stepped'])

    deliver(poll('w1', 2, [11, 21.5]))
    deliver(poll('w2', 3, [true]))
    expect(screen.getByTestId('chart-value-w1:1')).toHaveTextContent('21.5 m')
    expect(screen.getByTestId('chart-value-w2:0')).toHaveTextContent('1')
    expect(lastPlot().data).toEqual([
      [t0 + 1, t0 + 2, t0 + 3],
      [20, 21.5, undefined],
      [undefined, undefined, 1],
    ])
    expect(plots).toHaveLength(1)
  })

  it('pauses and resumes, and hides or removes series', () => {
    useStudio.getState().plot([
      { poll: 'w1', address: 0 },
      { poll: 'w1', address: 1 },
    ])
    render(<ChartPanel onClose={() => {}} />)
    deliver(poll('w1', 1, [1, 2]))

    fireEvent.click(screen.getByRole('button', { name: 'Pause' }))
    const calls = lastPlot().setDataCalls
    deliver(poll('w1', 2, [3, 4]))
    expect(lastPlot().setDataCalls).toBe(calls)
    expect(screen.getByTestId('chart-value-w1:1')).toHaveTextContent('2 m')
    fireEvent.click(screen.getByRole('button', { name: 'Resume' }))
    expect(screen.getByTestId('chart-value-w1:1')).toHaveTextContent('4 m')

    fireEvent.click(screen.getByText('level'))
    expect(lastPlot().shown[2]).toBe(false)
    expect(screen.getByText('level').closest('li')).toHaveClass('off')

    const first = lastPlot()
    fireEvent.click(screen.getByRole('button', { name: 'Remove level' }))
    expect(first.destroyed).toBe(true)
    expect(lastPlot().opts.series).toHaveLength(2)
    expect(useStudio.getState().plotted).toEqual([{ poll: 'w1', address: 0 }])
  })

  it('points out selected rows that are not plotted yet', () => {
    const { plot, setSelected } = useStudio.getState()
    plot([{ poll: 'w1', address: 0 }])
    setSelected('w1', [0, 1])
    setSelected('w2', [3])
    render(<ChartPanel onClose={() => {}} />)
    expect(screen.getByRole('status')).toHaveTextContent(
      '2 selected rows in Tank, Pumps not on the chart yet — press Plot or Plot them',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Plot them' }))
    expect(useStudio.getState().plotted).toEqual([
      { poll: 'w1', address: 0 },
      { poll: 'w1', address: 1 },
      { poll: 'w2', address: 3 },
    ])
    expect(screen.queryByRole('status')).toBeNull()
  })

  it('exports what it shows as CSV', () => {
    useStudio.getState().plot([{ poll: 'w1', address: 1 }])
    render(<ChartPanel onClose={() => {}} />)
    deliver(poll('w1', 1, [1, 2.5]))
    fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
    const [name, text] = vi.mocked(downloadText).mock.calls[0]
    expect(name).toMatch(/^modbus-chart-\d{8}-\d{4}\.csv$/)
    expect(text.split('\n')[0]).toBe('time,unix_s,level (m)')
    expect(text.split('\n')[1]).toMatch(/,2\.5$/)
  })
})
