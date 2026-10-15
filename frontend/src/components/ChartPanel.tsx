import { useEffect, useMemo, useRef, useState } from 'react'
import uPlot from 'uplot'
import 'uplot/dist/uPlot.min.css'
import {
  COLORS,
  MAX_SERIES,
  SPANS,
  alignSeries,
  alignedToCsv,
  formatNumber,
  seriesId,
  valuesAt,
  type Aligned,
  type SeriesKey,
} from '../chart'
import { useStudio } from '../store'
import { downloadText, fileTimestamp } from '../util'

/** How often the time axis slides when no new samples arrive. */
const TICK_MS = 500

interface SeriesInfo {
  key: SeriesKey
  id: string
  color: string
  label: string
  /** Window name and address, shown next to an alias. */
  source: string
  unit: string
  /** Coils and discrete inputs are drawn as steps. */
  bit: boolean
}

/** What the chart shows: live, or what it showed when paused. */
interface View {
  data: Aligned
  from: number
  to: number
  /** Series layout the data belongs to; a different layout resumes. */
  layout: string
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/** Real-time chart of the values selected with Plot in the polling windows. */
export function ChartPanel({ onClose }: { onClose: () => void }) {
  const plotted = useStudio((s) => s.plotted)
  const polls = useStudio((s) => s.polls)
  const cells = useStudio((s) => s.cells)
  const history = useStudio((s) => s.history)
  const unplot = useStudio((s) => s.unplot)
  const clearHistory = useStudio((s) => s.clearHistory)
  const selected = useStudio((s) => s.selected)
  const plot = useStudio((s) => s.plot)
  const [span, setSpan] = useState(60)
  const [now, setNow] = useState(() => Date.now() / 1000)
  const [frozen, setFrozen] = useState<View | null>(null)
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())
  const [cursor, setCursor] = useState<number | null>(null)
  const plotRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<uPlot | null>(null)

  const series: SeriesInfo[] = plotted.map((key, i) => {
    const def = polls[key.poll]?.definition
    const cell = cells[key.poll]?.find((c) => c.address === key.address)
    const alias = def?.formats[key.address]?.alias || cell?.alias || ''
    const source = `${def?.name || key.poll} @ ${key.address}`
    return {
      key,
      id: seriesId(key),
      color: COLORS[i % COLORS.length],
      label: alias || source,
      source,
      unit: cell?.unit ?? def?.formats[key.address]?.unit ?? '',
      bit: (def?.function ?? 3) <= 2,
    }
  })
  const layout = series.map((s) => `${s.id}${s.bit ? '/bit' : ''}/${s.unit}`).join(' ')

  const live = useMemo<View>(() => {
    const buffers = plotted.map((k) => history[seriesId(k)] ?? [])
    // A sample newer than the last tick must not fall off the right edge.
    const to = Math.max(now, ...buffers.map((b) => b[b.length - 1]?.t ?? 0))
    const from = to - span
    return { data: alignSeries(buffers, from), from, to, layout }
  }, [plotted, history, span, now, layout])

  const paused = frozen !== null && frozen.layout === layout
  const view = paused ? frozen : live

  useEffect(() => {
    if (paused) return
    const timer = setInterval(() => setNow(Date.now() / 1000), TICK_MS)
    return () => clearInterval(timer)
  }, [paused])
  // What the uPlot instance and its hooks read; kept current after every render.
  const latest = useRef({ view, series, hidden })
  useEffect(() => {
    latest.current = { view, series, hidden }
  })

  // A new uPlot for every series layout; data updates go through setData.
  useEffect(() => {
    const el = plotRef.current
    const { view, series, hidden } = latest.current
    if (!el || series.length === 0) return
    const muted = cssVar('--text-muted', '#8796a8')
    const grid = { stroke: cssVar('--border', '#253141'), width: 1 }
    const units = new Set(series.map((s) => s.unit))
    const unit = units.size === 1 ? [...units][0] : ''
    const chart = new uPlot(
      {
        width: el.clientWidth || 600,
        height: el.clientHeight || 200,
        legend: { show: false },
        cursor: { drag: { x: true, y: false } },
        scales: { x: { time: true } },
        axes: [
          { stroke: muted, grid, ticks: grid },
          { stroke: muted, grid, ticks: grid, size: 64, label: unit || undefined },
        ],
        series: [
          {},
          ...series.map((s) => ({
            label: s.label,
            stroke: s.color,
            width: 1.5,
            show: !hidden.has(s.id),
            paths: s.bit ? uPlot.paths.stepped?.({ align: 1 }) : undefined,
          })),
        ],
        hooks: {
          setCursor: [(u) => setCursor(u.cursor.idx ?? null)],
          // Dragging zooms in, which only makes sense on a chart that holds still.
          setSelect: [(u) => u.select.width > 0 && setFrozen((f) => f ?? latest.current.view)],
        },
      },
      view.data,
      el,
    )
    chart.setScale('x', { min: view.from, max: view.to })
    chartRef.current = chart
    const observer =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() =>
            chart.setSize({ width: el.clientWidth, height: el.clientHeight }),
          )
    observer?.observe(el)
    return () => {
      observer?.disconnect()
      chart.destroy()
      chartRef.current = null
      setCursor(null)
    }
    // Rebuilt only when the series change; data and visibility are updated in place.
  }, [layout])

  useEffect(() => {
    const chart = chartRef.current
    if (!chart || paused) return
    chart.batch(() => {
      chart.setData(view.data)
      chart.setScale('x', { min: view.from, max: view.to })
    })
  }, [view, paused])

  const toggle = (s: SeriesInfo, index: number) => {
    const show = hidden.has(s.id)
    chartRef.current?.setSeries(index + 1, { show })
    setHidden((h) => {
      const next = new Set(h)
      if (show) next.delete(s.id)
      else next.add(s.id)
      return next
    })
  }

  const values = valuesAt(view.data, cursor ?? undefined)

  // Rows selected in the windows that are not on the chart yet.
  const pending = Object.entries(selected).flatMap(([poll, addresses]) =>
    addresses
      .filter((address) => !plotted.some((k) => k.poll === poll && k.address === address))
      .map((address) => ({ poll, address })),
  )
  const pendingWindows = [...new Set(pending.map((k) => polls[k.poll]?.definition.name || k.poll))]
  const room = MAX_SERIES - plotted.length

  const exportCsv = () =>
    downloadText(
      `modbus-chart-${fileTimestamp()}.csv`,
      alignedToCsv(
        series.map((s) => (s.unit ? `${s.label} (${s.unit})` : s.label)),
        view.data,
        view.from,
      ),
      'text/csv',
    )

  return (
    <section className="chart" aria-label="Chart">
      <div className="traffic-bar">
        <h2>Chart</h2>
        <select
          aria-label="Time span"
          value={span}
          onChange={(e) => {
            setSpan(Number(e.target.value))
            setFrozen(null)
          }}
        >
          {SPANS.map((s) => (
            <option key={s.seconds} value={s.seconds}>
              {s.label}
            </option>
          ))}
        </select>
        <span className="muted">
          {paused ? 'paused · drag to zoom, double-click to reset' : 'drag to zoom'}
        </span>
        <span className="grow" />
        <button
          className="btn btn-small"
          aria-pressed={paused}
          disabled={series.length === 0}
          onClick={() => setFrozen(paused ? null : live)}
        >
          {paused ? 'Resume' : 'Pause'}
        </button>
        <button
          className="btn btn-small"
          disabled={view.data[0].length === 0}
          onClick={exportCsv}
        >
          Export CSV
        </button>
        <button
          className="btn btn-small"
          disabled={series.length === 0}
          title="Forget the samples recorded so far"
          onClick={() => {
            clearHistory()
            setFrozen(null)
          }}
        >
          Clear
        </button>
        <button className="btn btn-small" onClick={onClose}>
          Close
        </button>
      </div>
      {pending.length > 0 && (
        <div className="chart-pending" role="status">
          {pending.length} selected {pending.length === 1 ? 'row' : 'rows'} in{' '}
          {pendingWindows.join(', ')} not on the chart yet — press <strong>Plot</strong>
          {room > 0 ? (
            <>
              {' '}
              or{' '}
              <button className="btn btn-small" onClick={() => plot(pending)}>
                Plot {pending.length > room ? `the first ${room}` : 'them'}
              </button>
            </>
          ) : (
            ` after removing a series (the chart holds ${MAX_SERIES}).`
          )}
        </div>
      )}
      {series.length === 0 ? (
        <div className="chart-empty muted">
          Select rows in a polling window and press <strong>Plot</strong> to chart them.
        </div>
      ) : (
        <div className="chart-body">
          <ul className="chart-legend" aria-label="Series">
            {series.map((s, i) => {
              const value = values[i]
              return (
                <li key={s.id} className={hidden.has(s.id) ? 'off' : undefined}>
                  <button
                    className="chart-series"
                    aria-pressed={!hidden.has(s.id)}
                    title={`${s.source} · click to ${hidden.has(s.id) ? 'show' : 'hide'}`}
                    onClick={() => toggle(s, i)}
                  >
                    <span className="swatch" style={{ background: s.color }} />
                    <span className="label">{s.label}</span>
                  </button>
                  <span className="mono value" data-testid={`chart-value-${s.id}`}>
                    {value === null ? '—' : formatNumber(value)}
                    {s.unit && value !== null && <span className="unit"> {s.unit}</span>}
                  </span>
                  <button
                    className="btn btn-small"
                    aria-label={`Remove ${s.label}`}
                    onClick={() => unplot([s.key])}
                  >
                    ✕
                  </button>
                </li>
              )
            })}
          </ul>
          <div className="chart-plot" ref={plotRef} />
        </div>
      )}
    </section>
  )
}
