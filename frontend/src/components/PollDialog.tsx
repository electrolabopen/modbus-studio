import { useState } from 'react'
import { api } from '../api/client'
import {
  DEFAULT_FORMAT,
  FUNCTION_LABELS,
  type PollDefinition,
  type PollView,
  type ReadFunction,
} from '../api/types'
import { useStudio } from '../store'
import { Field, Modal } from './Modal'

interface PollDialogProps {
  /** Existing window to edit; omitted to create a new one. */
  existing?: PollView
  onClose: () => void
}

export function PollDialog({ existing, onClose }: PollDialogProps) {
  const connections = useStudio((s) => s.connections)
  const upsert = useStudio((s) => s.upsertPoll)
  const pollCount = useStudio((s) => Object.keys(s.polls).length)
  const connectionIds = Object.keys(connections)

  const [def, setDef] = useState<PollDefinition>(
    () =>
      existing?.definition ?? {
        connection_id: connectionIds[0] ?? '',
        name: `Poll ${pollCount + 1}`,
        device_id: 1,
        function: 3,
        address: 0,
        quantity: 10,
        scan_rate_ms: 1000,
        enabled: true,
        default_format: DEFAULT_FORMAT,
        formats: {},
      },
  )
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof PollDefinition>(key: K, value: PollDefinition[K]) =>
    setDef((d) => ({ ...d, [key]: value }))

  const maxQuantity = def.function <= 2 ? 2000 : 125

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const view = existing
        ? await api.updatePoll(existing.definition.id, def)
        : await api.createPoll(def)
      upsert(view)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const num = (key: 'device_id' | 'address' | 'quantity' | 'scan_rate_ms') =>
    (e: React.ChangeEvent<HTMLInputElement>) => set(key, e.target.valueAsNumber)

  return (
    <Modal
      title={existing ? 'Window definition' : 'New polling window'}
      submitLabel={existing ? 'Apply' : 'Create'}
      busy={busy}
      error={error}
      onSubmit={submit}
      onClose={onClose}
    >
      <Field label="Name">
        <input value={def.name} onChange={(e) => set('name', e.target.value)} />
      </Field>
      <Field label="Connection">
        <select
          value={def.connection_id}
          required
          onChange={(e) => set('connection_id', e.target.value)}
        >
          {connectionIds.map((id) => {
            const c = connections[id].config
            const where = 'host' in c ? `${c.host}:${c.port}` : c.serial_port
            return (
              <option key={id} value={id}>
                {c.name || id} — {where}
              </option>
            )
          })}
        </select>
      </Field>
      <div className="field-row">
        <Field label="Slave ID">
          <input type="number" min={0} max={255} value={def.device_id} required onChange={num('device_id')} />
        </Field>
        <Field label="Function">
          <select
            value={def.function}
            onChange={(e) => set('function', Number(e.target.value) as ReadFunction)}
          >
            {([1, 2, 3, 4] as ReadFunction[]).map((f) => (
              <option key={f} value={f}>
                {FUNCTION_LABELS[f]}
              </option>
            ))}
          </select>
        </Field>
      </div>
      <div className="field-row">
        <Field label="Address">
          <input type="number" min={0} max={65535} value={def.address} required onChange={num('address')} />
        </Field>
        <Field label={`Quantity (max ${maxQuantity})`}>
          <input
            type="number"
            min={1}
            max={maxQuantity}
            value={def.quantity}
            required
            onChange={num('quantity')}
          />
        </Field>
      </div>
      <Field label="Scan rate (ms)">
        <input
          type="number"
          min={10}
          max={3600000}
          value={def.scan_rate_ms}
          required
          onChange={num('scan_rate_ms')}
        />
      </Field>
      <p className="hint">Addresses are 0-based protocol addresses (as sent in the request).</p>
    </Modal>
  )
}
