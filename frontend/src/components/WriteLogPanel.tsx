import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { WriteLogEntry } from '../api/types'
import { useStudio } from '../store'

const pad = (n: number) => String(n).padStart(2, '0')

function formatTime(timestamp: number): { short: string; full: string } {
  const d = new Date(timestamp * 1000)
  const short = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  return { short, full: d.toLocaleString() }
}

const withUnit = (text: string | null, unit: string) =>
  text === null ? '—' : unit ? `${text} ${unit}` : text

/** Every write sent to a device, newest first. Kept on the server (/data/writes.jsonl). */
export function WriteLogPanel({ onClose }: { onClose: () => void }) {
  const writes = useStudio((s) => s.writes)
  const setWrites = useStudio((s) => s.setWrites)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .listWrites()
      .then((entries) => {
        if (cancelled) return
        // Entries pushed over the WebSocket meanwhile are newer than the fetched list.
        const live = useStudio.getState().writes
        const seen = new Set(entries.map((e) => e.seq))
        setWrites([...live.filter((e) => !seen.has(e.seq)), ...entries])
      })
      .catch((err: unknown) => !cancelled && setError(String(err)))
    return () => {
      cancelled = true
    }
  }, [setWrites])

  return (
    <section className="write-log" aria-label="Write log">
      <header>
        <h2>Write log</h2>
        <span className="muted small">{writes.length} entries · newest first</span>
        <button className="btn btn-small" style={{ marginLeft: 'auto' }} onClick={onClose}>
          Close
        </button>
      </header>
      {error && <p className="form-error">{error}</p>}
      <div className="table-wrap">
        <table className="mono">
          <thead>
            <tr>
              <th>Time</th>
              <th>Connection</th>
              <th>ID</th>
              <th>FC</th>
              <th>Address</th>
              <th>Old → New</th>
              <th>Raw</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {writes.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No writes yet.
                </td>
              </tr>
            )}
            {writes.map((w) => (
              <WriteRow key={w.seq} entry={w} />
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function WriteRow({ entry: w }: { entry: WriteLogEntry }) {
  const time = formatTime(w.timestamp)
  return (
    <tr className={w.ok ? undefined : 'failed'}>
      <td title={time.full}>{time.short}</td>
      <td>{w.connection_name || w.connection_id}</td>
      <td>{w.device_id}</td>
      <td>{String(w.function).padStart(2, '0')}</td>
      <td>
        {w.address}
        {w.alias && <span className="muted"> {w.alias}</span>}
      </td>
      <td>
        {withUnit(w.old, w.unit)} <span className="arrow">→</span> {withUnit(w.new, w.unit)}
      </td>
      <td>{w.values.join(' ')}</td>
      <td>{w.ok ? 'OK' : w.error}</td>
    </tr>
  )
}
