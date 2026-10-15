import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import { COLORS, MAX_SERIES, sameSeries } from '../chart'
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
import { CsvImportDialog } from './CsvImportDialog'
import { FormatDialog } from './FormatDialog'
import { PollDialog } from './PollDialog'
import { WriteDialog } from './WriteDialog'

const NO_CELLS: Cell[] = []

function errorText(data: PollData): string {
  switch (data.error_kind) {
    case 'timeout':
      return 'Timeout error'
    case 'disconnected':
      return data.error && data.error !== 'not connected'
        ? `No connection: ${data.error}`
        : 'No connection'
    case 'invalid':
      return `Invalid response: ${data.error ?? ''}`
    default:
      return data.error ?? 'Error'
  }
}

/** Address of the cell that displays ``address`` (itself, or the 32/64-bit value covering it). */
const ownerOf = (cells: Cell[], address: number) =>
  cells.find((c) => c.address === address)?.covered_by ?? address

/** Last register of the value that starts at ``address``. */
function lastRegisterOf(cells: Cell[], address: number): number {
  let last = address
  for (const c of cells) if (c.covered_by === address) last = Math.max(last, c.address)
  return last
}

export function PollWindow({ view }: { view: PollView }) {
  const def = view.definition
  const latest = useStudio((s) => s.latest[def.id])
  const cells = useStudio((s) => s.cells[def.id] ?? NO_CELLS)
  const upsert = useStudio((s) => s.upsertPoll)
  const connection = useStudio((s) => s.connections[def.connection_id])
  const [editing, setEditing] = useState(false)
  const [writing, setWriting] = useState<Cell | null>(null)
  const [formatting, setFormatting] = useState<{ start: number; end: number } | null>(null)
  const [aliasEditing, setAliasEditing] = useState<number | null>(null)
  const [selection, setSelection] = useState<{ anchor: number; focus: number } | null>(null)
  const [csvFile, setCsvFile] = useState<File | null>(null)
  const csvInput = useRef<HTMLInputElement>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const plotted = useStudio((s) => s.plotted)
  const plot = useStudio((s) => s.plot)
  const setSelected = useStudio((s) => s.setSelected)
  const unplot = useStudio((s) => s.unplot)

  const stats = latest?.stats ?? view.stats
  const isBit = def.function <= 2
  const fc = String(def.function).padStart(2, '0')
  const readOnly = connection?.config.read_only ?? false
  // FC02/FC04 data cannot be written by any Modbus function.
  const writable = (def.function === 1 || def.function === 3) && !readOnly

  // A selection always covers whole values: never half of a 32/64-bit register pair.
  const selected = selection && {
    start: ownerOf(cells, Math.min(selection.anchor, selection.focus)),
    end: lastRegisterOf(
      cells,
      ownerOf(cells, Math.max(selection.anchor, selection.focus)),
    ),
  }

  // One series per value: the first register of a 32/64-bit value stands for it.
  const toPlot = selected
    ? cells
        .filter((c) => c.covered_by === null && c.address >= selected.start && c.address <= selected.end)
        .map((c) => ({ poll: def.id, address: c.address }))
    : []
  // Tell the chart panel, which offers to plot what is selected.
  const selectedKey = toPlot.map((k) => k.address).join(',')
  useEffect(() => {
    setSelected(def.id, selectedKey ? selectedKey.split(',').map(Number) : [])
    return () => setSelected(def.id, [])
  }, [def.id, selectedKey, setSelected])

  const allPlotted =
    toPlot.length > 0 && toPlot.every((k) => plotted.some((p) => sameSeries(p, k)))
  const colorOf = (address: number) => {
    const i = plotted.findIndex((p) => p.poll === def.id && p.address === address)
    return i < 0 ? null : COLORS[i % COLORS.length]
  }

  const togglePlot = () => {
    setActionError(null)
    if (allPlotted) {
      unplot(toPlot)
      return
    }
    const left = plot(toPlot)
    if (left > 0)
      setActionError(
        `The chart holds ${MAX_SERIES} values; ${left} of the selected were not added.`,
      )
  }

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

  const openFormat = (address: number) => {
    if (isBit) return
    const start = ownerOf(cells, address)
    setSelection({ anchor: start, focus: start })
    setFormatting({ start, end: start })
  }

  const saveAlias = (address: number, alias: string) => {
    setAliasEditing(null)
    if (alias === (def.formats[address]?.alias ?? '')) return
    run(() => api.patchFormats(def.id, { start: address, end: address, alias }))
  }

  const select = (address: number, extend: boolean) =>
    setSelection((s) =>
      extend && s ? { anchor: s.anchor, focus: address } : { anchor: address, focus: address },
    )

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
                title="Window default format"
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
                title="Window default byte order"
                value={def.default_format.order}
                onChange={(e) => setFormat({ order: e.target.value as ByteOrder })}
              >
                {BYTE_ORDERS.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
              <button
                className="btn btn-small"
                disabled={!selected}
                title={
                  selected
                    ? `Format addresses ${selected.start}–${selected.end}`
                    : 'Select rows first (Shift+click selects a range)'
                }
                onClick={() => selected && setFormatting(selected)}
              >
                Format…
              </button>
            </>
          )}
          <button
            className="btn btn-small"
            disabled={toPlot.length === 0}
            aria-pressed={allPlotted}
            title={
              toPlot.length === 0
                ? 'Select rows to chart them'
                : allPlotted
                  ? 'Take the selected values off the chart'
                  : 'Add the selected values to the chart'
            }
            onClick={togglePlot}
          >
            {allPlotted ? 'Unplot' : 'Plot'}
          </button>
          <button
            className="btn btn-small"
            title="Import a CSV register map (address, alias, type, byte_order, scale, unit)"
            onClick={() => csvInput.current?.click()}
          >
            Import CSV map…
          </button>
          <input
            ref={csvInput}
            type="file"
            accept=".csv,text/csv,text/plain"
            hidden
            aria-label="CSV register map file"
            onChange={(e) => {
              setCsvFile(e.target.files?.[0] ?? null)
              e.target.value = '' // picking the same file again must fire onChange
            }}
          />
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
              <th title={isBit ? undefined : 'Double-click: cell format'}>Address</th>
              <th title="Double-click to edit">Alias</th>
              <th title={writable ? 'Double-click to write' : undefined}>Value</th>
            </tr>
          </thead>
          <tbody>
            {cells.map((c) => {
              const isSelected =
                selected !== null && c.address >= selected.start && c.address <= selected.end
              const classes = [
                c.covered_by !== null && 'covered',
                writable && 'writable',
                isSelected && 'selected',
              ]
              const alias = c.covered_by === null ? (def.formats[c.address]?.alias ?? c.alias) : ''
              const color = colorOf(c.address)
              return (
                <tr
                  key={c.address}
                  className={classes.filter(Boolean).join(' ') || undefined}
                  aria-selected={isSelected}
                  onClick={(e) => select(c.address, e.shiftKey)}
                >
                  <td className="addr" onDoubleClick={() => openFormat(c.address)}>
                    {c.address}
                    {color && (
                      <span
                        className="plot-dot"
                        style={{ background: color }}
                        title="On the chart"
                        data-testid={`plotted-${c.address}`}
                      />
                    )}
                  </td>
                  <td
                    className="alias"
                    onDoubleClick={() => setAliasEditing(ownerOf(cells, c.address))}
                  >
                    {aliasEditing === c.address ? (
                      <AliasEditor
                        initial={alias}
                        onSave={(value) => saveAlias(c.address, value)}
                        onCancel={() => setAliasEditing(null)}
                      />
                    ) : (
                      alias
                    )}
                  </td>
                  <td
                    className="value"
                    title={
                      c.error ?? `raw: ${c.raw.join(' ')}${writable ? ' · double-click to write' : ''}`
                    }
                    onDoubleClick={() => openWrite(c)}
                  >
                    {c.text}
                    {c.unit && <span className="unit"> {c.unit}</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {editing && <PollDialog existing={view} onClose={() => setEditing(false)} />}
      {writing && <WriteDialog view={view} cell={writing} onClose={() => setWriting(null)} />}
      {csvFile && <CsvImportDialog view={view} file={csvFile} onClose={() => setCsvFile(null)} />}
      {formatting && (
        <FormatDialog
          view={view}
          start={formatting.start}
          end={formatting.end}
          onClose={() => setFormatting(null)}
        />
      )}
    </section>
  )
}

function AliasEditor({
  initial,
  onSave,
  onCancel,
}: {
  initial: string
  onSave: (alias: string) => void
  onCancel: () => void
}) {
  const [value, setValue] = useState(initial)
  // Enter and the blur that follows it must not save twice.
  const done = useRef(false)
  const finish = (save: boolean) => {
    if (done.current) return
    done.current = true
    if (save) onSave(value.trim())
    else onCancel()
  }
  return (
    <input
      className="alias-input"
      aria-label="Alias"
      autoFocus
      maxLength={64}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === 'Enter') finish(true)
        else if (e.key === 'Escape') finish(false)
      }}
      onBlur={() => finish(true)}
    />
  )
}
