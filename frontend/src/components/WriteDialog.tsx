import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  WRITE_FUNCTION_LABELS,
  type Cell,
  type PollView,
  type WindowWrite,
  type WritePlan,
} from '../api/types'
import { useStudio } from '../store'
import { Field, Modal } from './Modal'

const PREVIEW_DELAY_MS = 200

const hex4 = (v: number) => `0x${v.toString(16).toUpperCase().padStart(4, '0')}`

/** Accepts decimal, scientific and 0x / 0b literals ("0x1F", "0b1010"). */
function parseNumber(text: string): number | null {
  const trimmed = text.trim()
  if (trimmed === '') return null
  const negative = trimmed.startsWith('-')
  const body = negative ? trimmed.slice(1) : trimmed
  const value = /^0[xb]/i.test(body) ? Number(body) * (negative ? -1 : 1) : Number(trimmed)
  return Number.isFinite(value) ? value : null
}

interface Props {
  view: PollView
  cell: Cell
  onClose: () => void
}

/** Confirm a write: shows the function, address, value and the raw data sent. */
export function WriteDialog({ view, cell, onClose }: Props) {
  const def = view.definition
  const isCoil = def.function === 1
  const connection = useStudio((s) => s.connections[def.connection_id])
  const [text, setText] = useState(() => (cell.value === null ? '' : String(Number(cell.value))))
  const [coil, setCoil] = useState(() => !cell.value)
  const [forceMultiple, setForceMultiple] = useState(false)
  // Keyed by the request it answers, so a stale preview is never shown or confirmed.
  const [preview, setPreview] = useState<{ key: string; plan?: WritePlan; error?: string }>()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const value = isCoil ? coil : parseNumber(text)
  const req: WindowWrite | null =
    value === null ? null : { address: cell.address, value, force_multiple: forceMultiple }
  const key = JSON.stringify(req)

  useEffect(() => {
    const request = JSON.parse(key) as WindowWrite | null
    if (request === null) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      api
        .previewWrite(def.id, request, controller.signal)
        .then((plan) => setPreview({ key, plan }))
        .catch((err: unknown) => {
          if (controller.signal.aborted) return
          setPreview({ key, error: err instanceof Error ? err.message : String(err) })
        })
    }, PREVIEW_DELAY_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [key, def.id])

  const answered = req !== null && preview?.key === key ? preview : undefined
  const current = answered?.plan ?? null
  const inputError = req === null ? 'Enter a number (decimal, 0x… or 0b…)' : answered?.error

  const submit = async () => {
    if (!current || req === null) return
    setBusy(true)
    setError(null)
    try {
      await api.write(def.id, req)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const where = connection?.config.name || def.connection_id

  return (
    <Modal
      title={isCoil ? 'Write coil' : 'Write register'}
      submitLabel="Write"
      busy={busy || !current}
      error={error}
      onSubmit={submit}
      onClose={onClose}
      focusCancel
    >
      <p className="hint">
        {where} · device {def.device_id} · address {cell.address}
        {cell.alias && ` (${cell.alias})`}
      </p>

      {isCoil ? (
        <Field label="New state">
          <select
            value={coil ? '1' : '0'}
            onChange={(e) => setCoil(e.target.value === '1')}
          >
            <option value="1">1 · ON</option>
            <option value="0">0 · OFF</option>
          </select>
        </Field>
      ) : (
        <Field label={`Value${cell.unit ? ` (${cell.unit})` : ''}`}>
          <input
            inputMode="decimal"
            value={text}
            onFocus={(e) => e.target.select()}
            onChange={(e) => setText(e.target.value)}
          />
        </Field>
      )}

      <label className="check">
        <input
          type="checkbox"
          checked={forceMultiple}
          onChange={(e) => setForceMultiple(e.target.checked)}
        />
        Always use {isCoil ? 'FC15' : 'FC16'} (for devices without {isCoil ? 'FC05' : 'FC06'})
      </label>

      {inputError && <p className="form-error">{inputError}</p>}

      {current && (
        <dl className="write-plan" aria-label="Write preview">
          <dt>Function</dt>
          <dd>{WRITE_FUNCTION_LABELS[current.function]}</dd>
          <dt>Address</dt>
          <dd className="mono">
            {current.address}
            {current.values.length > 1 && `–${current.address + current.values.length - 1}`}
          </dd>
          {current.dtype && (
            <>
              <dt>Format</dt>
              <dd className="mono">
                {current.dtype} · {current.order}
                {current.scale !== 1 && ` · scale ${current.scale}`}
              </dd>
            </>
          )}
          <dt>Value</dt>
          <dd className="mono">
            {current.text}
            {current.unit && ` ${current.unit}`}
          </dd>
          <dt>Raw</dt>
          <dd className="mono" data-testid="write-raw">
            {isCoil
              ? current.values.join(' ')
              : current.values.map((v) => `${hex4(v)} (${v})`).join('  ')}
          </dd>
        </dl>
      )}
      {current?.rounded && (
        <p className="warning" role="status">
          {String(current.requested)} cannot be stored exactly; the device will hold{' '}
          {current.text}
          {current.unit && ` ${current.unit}`}.
        </p>
      )}
    </Modal>
  )
}
