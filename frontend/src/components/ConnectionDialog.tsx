import { useState } from 'react'
import { api } from '../api/client'
import type { TcpConnection } from '../api/types'
import { useStudio } from '../store'
import { Field, Modal } from './Modal'

export function ConnectionDialog({ onClose }: { onClose: () => void }) {
  const upsert = useStudio((s) => s.upsertConnection)
  const [type, setType] = useState<TcpConnection['type']>('tcp')
  const [name, setName] = useState('')
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState(5020)
  const [timeoutMs, setTimeoutMs] = useState(1000)
  const [readOnly, setReadOnly] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    try {
      const view = await api.createConnection({
        type,
        name: name.trim(),
        host: host.trim(),
        port,
        timeout_s: timeoutMs / 1000,
        retries: 0,
        delay_between_requests_ms: 0,
        read_only: readOnly,
      })
      upsert(view)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="New connection" submitLabel="Create" busy={busy} error={error} onSubmit={submit} onClose={onClose}>
      <Field label="Mode">
        <select value={type} onChange={(e) => setType(e.target.value as TcpConnection['type'])}>
          <option value="tcp">Modbus TCP</option>
          <option value="rtu_over_tcp">RTU over TCP</option>
        </select>
      </Field>
      <Field label="Name">
        <input value={name} placeholder="optional" onChange={(e) => setName(e.target.value)} />
      </Field>
      <div className="field-row">
        <Field label="IP address / host">
          <input value={host} required onChange={(e) => setHost(e.target.value)} />
        </Field>
        <Field label="Port">
          <input
            type="number"
            min={1}
            max={65535}
            value={port}
            required
            onChange={(e) => setPort(e.target.valueAsNumber)}
          />
        </Field>
      </div>
      <p className="hint">
        Running in docker compose? Use the service name (e.g. <code>simulator</code>):
        127.0.0.1 there is the modbus-studio container itself.
      </p>
      <Field label="Response timeout (ms)">
        <input
          type="number"
          min={10}
          max={60000}
          value={timeoutMs}
          required
          onChange={(e) => setTimeoutMs(e.target.valueAsNumber)}
        />
      </Field>
      <label className="check">
        <input type="checkbox" checked={readOnly} onChange={(e) => setReadOnly(e.target.checked)} />
        Read-only: block all writes on this connection
      </label>
    </Modal>
  )
}
