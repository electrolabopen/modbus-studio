import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api/client'
import { setTrafficSubscription } from '../api/socket'
import type { TrafficEntry } from '../api/types'
import { MAX_FRAMES, useStudio } from '../store'
import {
  NO_FILTER,
  countTraffic,
  describeEntry,
  filterTraffic,
  isProblem,
  mergeFrames,
  responseTimes,
  trafficToCsv,
  type TrafficFilter,
} from '../traffic'
import { clockTime, downloadText, fileTimestamp } from '../util'

/** Rows rendered; the filter, counters and export still use every frame. */
const MAX_ROWS = 500

/** Raw TX/RX frames with filters, pause, counters and CSV export. */
export function TrafficPanel({ onClose }: { onClose: () => void }) {
  const live = useStudio((s) => s.traffic)
  const connections = useStudio((s) => s.connections)
  const setTraffic = useStudio((s) => s.setTraffic)
  const [filter, setFilter] = useState<TrafficFilter>(NO_FILTER)
  // While paused the view keeps the frames it had; new ones still arrive in the store.
  const [frozen, setFrozen] = useState<TrafficEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)

  useEffect(() => {
    setTrafficSubscription(true)
    let cancelled = false
    api
      .listTraffic(MAX_FRAMES)
      .then((saved) => {
        if (!cancelled) setTraffic(mergeFrames(saved, useStudio.getState().traffic))
      })
      .catch((err: unknown) => !cancelled && setError(String(err)))
    return () => {
      cancelled = true
      setTrafficSubscription(false)
    }
  }, [setTraffic])

  const entries = frozen ?? live
  const times = useMemo(() => responseTimes(entries), [entries])
  const matching = useMemo(() => filterTraffic(entries, filter), [entries, filter])
  const counts = useMemo(() => countTraffic(matching), [matching])
  const shown = matching.length > MAX_ROWS ? matching.slice(-MAX_ROWS) : matching
  const lastFrozen = frozen?.[frozen.length - 1]?.seq ?? 0
  const arrivedWhilePaused = frozen ? live.filter((e) => e.seq > lastFrozen).length : 0

  useLayoutEffect(() => {
    const el = listRef.current
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight
  }, [shown])

  const names = Object.fromEntries(
    Object.values(connections).map((c) => [c.config.id, c.config.name || c.config.id]),
  )
  const set = (patch: Partial<TrafficFilter>) => setFilter((f) => ({ ...f, ...patch }))

  const clear = async () => {
    setError(null)
    try {
      await api.clearTraffic()
      setTraffic([])
      if (frozen) setFrozen([])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const exportCsv = () =>
    downloadText(
      `modbus-traffic-${fileTimestamp()}.csv`,
      trafficToCsv(matching, names, times),
      'text/csv',
    )

  return (
    <section className="traffic" aria-label="Traffic monitor">
      <div className="traffic-bar">
        <h2>Traffic</h2>
        <select
          aria-label="Connection"
          value={filter.connection}
          onChange={(e) => set({ connection: e.target.value })}
        >
          <option value="">All connections</option>
          {Object.entries(names).map(([id, name]) => (
            <option key={id} value={id}>
              {name}
            </option>
          ))}
        </select>
        <select
          aria-label="Direction"
          value={filter.direction}
          onChange={(e) => set({ direction: e.target.value as TrafficFilter['direction'] })}
        >
          <option value="all">TX + RX</option>
          <option value="tx">TX only</option>
          <option value="rx">RX only</option>
        </select>
        <label>
          ID{' '}
          <input
            className="narrow"
            aria-label="Device ID"
            value={filter.device}
            onChange={(e) => set({ device: e.target.value })}
          />
        </label>
        <label>
          FC{' '}
          <input
            className="narrow"
            aria-label="Function code"
            value={filter.fn}
            onChange={(e) => set({ fn: e.target.value })}
          />
        </label>
        <input
          aria-label="Search hex"
          placeholder="hex, e.g. 01 03"
          value={filter.search}
          onChange={(e) => set({ search: e.target.value })}
        />
        <label>
          <input
            type="checkbox"
            checked={filter.problemsOnly}
            onChange={(e) => set({ problemsOnly: e.target.checked })}
          />{' '}
          Errors only
        </label>
        <span className="grow" />
        <button
          className="btn btn-small"
          aria-pressed={frozen !== null}
          onClick={() => setFrozen((f) => (f ? null : live))}
        >
          {frozen ? 'Resume' : 'Pause'}
        </button>
        <button className="btn btn-small" disabled={matching.length === 0} onClick={exportCsv}>
          Export CSV
        </button>
        <button className="btn btn-small" onClick={clear}>
          Clear
        </button>
        <button className="btn btn-small" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="traffic-counts" data-testid="traffic-counts">
        TX {counts.tx} · RX {counts.rx} ·{' '}
        <span className={counts.exceptions ? 'bad' : undefined}>
          exceptions {counts.exceptions}
        </span>{' '}
        ·{' '}
        <span className={counts.malformed ? 'bad' : undefined}>
          malformed {counts.malformed}
        </span>
        {matching.length > MAX_ROWS && ` · showing the last ${MAX_ROWS} of ${matching.length}`}
        {frozen && (
          <span className="paused-note"> · paused, {arrivedWhilePaused} new frames</span>
        )}
        {error && <span className="bad"> · {error}</span>}
      </div>
      <div
        className="traffic-list mono"
        ref={listRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
        }}
      >
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Connection</th>
              <th>Dir</th>
              <th>ID</th>
              <th>FC</th>
              <th title="Response time: since the previous TX on the same connection">ms</th>
              <th>Info</th>
              <th>Bytes</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  {entries.length === 0 ? 'No frames yet.' : 'No frames match the filter.'}
                </td>
              </tr>
            )}
            {shown.map((e) => (
              <tr key={e.seq} className={`${e.direction}${isProblem(e) ? ' problem' : ''}`}>
                <td>{clockTime(e.timestamp)}</td>
                <td>{names[e.connection_id] ?? e.connection_id}</td>
                <td className="dir">{e.direction.toUpperCase()}</td>
                <td>{e.device_id ?? ''}</td>
                <td>{e.function === null ? '' : String(e.function).padStart(2, '0')}</td>
                <td>{times.has(e.seq) ? times.get(e.seq)!.toFixed(1) : ''}</td>
                <td>{describeEntry(e)}</td>
                <td className="hex">{e.hex}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
