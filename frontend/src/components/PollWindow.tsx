import { useState } from 'react'
import { api } from '../api/client'
import {
  BYTE_ORDERS,
  DATA_TYPES,
  type ByteOrder,
  type Cell,
  type DataType,
  type PollData,
  type PollView,
} from '../api/types'
import { useStudio } from '../store'
import { PollDialog } from './PollDialog'
import { WriteDialog } from './WriteDialog'

const NO_CELLS: Cell[] = []

function errorText(data: PollData): string {
  switch (data.error_kind) {
    case 'timeout':
      return 'Timeout error'
    case 'disconnected':
      return 'No connection'
    case 'invalid':
      return `Invalid response: ${data.error ?? ''}`
    default:
      return data.error ?? 'Error'
  }
}

export function PollWindow({ view }: { view: PollView }) {
  const def = view.definition
  const latest = useStudio((s) => s.latest[def.id])
  const cells = useStudio((s) => s.cells[def.id] ?? NO_CELLS)
  const upsert = useStudio((s) => s.upsertPoll)
  const connection = useStudio((s) => s.connections[def.connection_id])
  const [editing, setEditing] = useState(false)
  const [writing, setWriting] = useState<Cell | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const stats = latest?.stats ?? view.stats
  const isBit = def.function <= 2
  const fc = String(def.function).padStart(2, '0')
  const readOnly = connection?.config.read_only ?? false
  // FC02/FC04 data cannot be written by any Modbus function.
  const writable = (def.function === 1 || def.function === 3) && !readOnly

  const run = async (action: () => Promise<PollView | void>) => {
    setActionError(null)
    try {
      const result = await action()
      if (result) upsert(result)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err))
    }
  }

  const openWrite = (c: Cell) => {
    setActionError(null)
    if (def.function === 2 || def.function === 4) {
      setActionError(
        def.function === 2
          ? 'Discrete inputs are read-only in Modbus; open an FC01 window to write coils.'
          : 'Input registers are read-only in Modbus; open an FC03 window to write.',
      )
      return
    }
    if (readOnly) {
      const name = connection?.config.name || def.connection_id
      setActionError(`Connection "${name}" is read-only. Unlock it in the sidebar to write.`)
      return
    }
    // A continuation register belongs to the 32/64-bit value that starts before it.
    const first = c.covered_by === null ? c : (cells.find((x) => x.address === c.covered_by) ?? c)
    setWriting(first)
  }

  const setFormat = (patch: { dtype?: DataType; order?: ByteOrder }) =>
    run(() =>
      api.updatePoll(def.id, { ...def, default_format: { ...def.default_format, ...patch } }),
    )

  return (
    <section className="poll-window" aria-label={def.name || def.id}>
      <header className="poll-header">
        <h3>{def.name || def.id}</h3>
        <div className="poll-actions">
          {!isBit && (
            <>
              <select
                aria-label="Display format"
                value={def.default_format.dtype}
                onChange={(e) => setFormat({ dtype: e.target.value as DataType })}
              >
                {DATA_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
              <select
                aria-label="Byte order"
                value={def.default_format.order}
                onChange={(e) => setFormat({ order: e.target.value as ByteOrder })}
              >
                {BYTE_ORDERS.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            </>
          )}
          <button className="btn btn-small" onClick={() => run(() => api.resetPoll(def.id))}>
            Reset
          </button>
          <button className="btn btn-small" onClick={() => setEditing(true)}>
            Edit
          </button>
          <button
            className="btn btn-small"
            aria-label="Close window"
            onClick={() => run(() => api.deletePoll(def.id))}
          >
            ✕
          </button>
        </div>
      </header>

      <div className="poll-status mono" data-testid="poll-status">
        Tx = {stats.polls}: Err = {stats.errors}: ID = {def.device_id}: F = {fc}: SR = {def.scan_rate_ms}ms
        {readOnly && <span className="tag">read-only</span>}
      </div>
      {latest && !latest.ok && <div className="poll-error">{errorText(latest)}</div>}
      {!latest && <div className="poll-wait">Waiting for data…</div>}
      {actionError && <div className="poll-error">{actionError}</div>}

      <div className="poll-table-wrap">
        <table className="poll-table mono">
          <thead>
            <tr>
              <th>Address</th>
              <th>Alias</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {cells.map((c) => (
              <tr
                key={c.address}
                className={
                  [c.covered_by !== null && 'covered', writable && 'writable']
                    .filter(Boolean)
                    .join(' ') || undefined
                }
                onDoubleClick={() => openWrite(c)}
              >
                <td className="addr">{c.address}</td>
                <td className="alias">{c.alias}</td>
                <td
                  className="value"
                  title={
                    c.error ?? `raw: ${c.raw.join(' ')}${writable ? ' · double-click to write' : ''}`
                  }
                >
                  {c.text}
                  {c.unit && <span className="unit"> {c.unit}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {editing && <PollDialog existing={view} onClose={() => setEditing(false)} />}
      {writing && <WriteDialog view={view} cell={writing} onClose={() => setWriting(null)} />}
    </section>
  )
}
