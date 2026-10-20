import { useState } from 'react'
import { api } from '../api/client'
import {
  BYTE_ORDERS,
  DATA_TYPES,
  type ByteOrder,
  type DataType,
  type FormatPatch,
  type PollView,
} from '../api/types'
import { useStudio } from '../store'
import { Field, Modal } from './Modal'

const WIDTH: Partial<Record<DataType, number>> = {
  int32: 2,
  uint32: 2,
  float32: 2,
  int64: 4,
  uint64: 4,
  float64: 4,
}

interface Props {
  view: PollView
  start: number
  end: number
  onClose: () => void
}

/** Data type, byte order, scale and unit for one cell or a range of cells. */
export function FormatDialog({ view, start, end, onClose }: Props) {
  const def = view.definition
  const upsert = useStudio((s) => s.upsertPoll)
  const initial = def.formats[start] ?? def.default_format
  const [dtype, setDtype] = useState<DataType>(initial.dtype)
  const [order, setOrder] = useState<ByteOrder>(initial.order)
  const [scale, setScale] = useState(String(initial.scale))
  const [unit, setUnit] = useState(initial.unit)
  const initialDeadband = initial.deadband == null ? '' : String(initial.deadband)
  const [deadband, setDeadband] = useState(initialDeadband)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const width = WIDTH[dtype] ?? 1
  const parsedScale = Number(scale)
  const scaleValid = scale.trim() !== '' && Number.isFinite(parsedScale) && parsedScale !== 0
  const parsedDeadband = deadband.trim() === '' ? null : Number(deadband)
  const deadbandValid =
    parsedDeadband === null || (Number.isFinite(parsedDeadband) && parsedDeadband >= 0)
  // Sent only when edited, so a range keeps each cell's own deadband otherwise.
  const deadbandPatch = deadband.trim() === initialDeadband ? {} : { deadband: parsedDeadband }

  const send = async (patch: FormatPatch) => {
    setBusy(true)
    setError(null)
    try {
      upsert(await api.patchFormats(def.id, patch))
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const range = start === end ? `address ${start}` : `addresses ${start}–${end}`
  const values = Math.ceil((end - start + 1) / width)

  return (
    <Modal
      title="Cell format"
      submitLabel="Apply"
      busy={busy || !scaleValid || !deadbandValid}
      error={
        error ??
        (!scaleValid
          ? 'Scale must be a non-zero number'
          : !deadbandValid
            ? 'Deadband must be a number, 0 or more, or empty'
            : null)
      }
      onSubmit={() =>
        send({
          start,
          end,
          dtype,
          order,
          scale: parsedScale,
          unit: unit.trim(),
          ...deadbandPatch,
        })
      }
      onClose={onClose}
      secondary={{
        label: 'Reset to window format',
        onClick: () => send({ start, end, reset: true }),
      }}
    >
      <p className="hint">
        {def.name || def.id} · {range}
        {width > 1 &&
          ` · ${width} registers per value, ${values} value${values === 1 ? '' : 's'} starting at ${start}`}
      </p>
      <div className="field-row">
        <Field label="Data type">
          <select autoFocus value={dtype} onChange={(e) => setDtype(e.target.value as DataType)}>
            {DATA_TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Byte order">
          <select
            value={order}
            title="16-bit types only use the byte swap (BADC/DCBA)"
            onChange={(e) => setOrder(e.target.value as ByteOrder)}
          >
            {BYTE_ORDERS.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </Field>
      </div>
      <div className="field-row">
        <Field label="Scale">
          <input inputMode="decimal" value={scale} onChange={(e) => setScale(e.target.value)} />
        </Field>
        <Field label="Unit">
          <input value={unit} maxLength={32} placeholder="e.g. °C" onChange={(e) => setUnit(e.target.value)} />
        </Field>
      </div>
      <p className="hint">Displayed value = raw value × scale. Writes divide by the scale.</p>
      <div className="field-row">
        <Field label="MQTT deadband">
          <input
            inputMode="decimal"
            value={deadband}
            placeholder="empty: the exporter's"
            onChange={(e) => setDeadband(e.target.value)}
          />
        </Field>
      </div>
      <p className="hint">
        When MQTT publishes on change: the smallest change of this value that is published, in
        engineering units (0: any change).
      </p>
    </Modal>
  )
}
