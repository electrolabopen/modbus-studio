import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ConnectionConfig, RtuConnection, SerialPort } from '../api/types'
import { useStudio } from '../store'
import { Field, Modal } from './Modal'

type Mode = ConnectionConfig['type']

const BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

/** "FTDI · VID:PID 0403:6001 · S/N A50285BI" */
function portDetails(p: SerialPort): string {
  const hex = (n: number) => n.toString(16).padStart(4, '0')
  return [
    p.manufacturer,
    p.vid !== null && p.pid !== null && `VID:PID ${hex(p.vid)}:${hex(p.pid)}`,
    p.serial_number && `S/N ${p.serial_number}`,
  ]
    .filter(Boolean)
    .join(' · ')
}

export function ConnectionDialog({ onClose }: { onClose: () => void }) {
  const upsert = useStudio((s) => s.upsertConnection)
  const [type, setType] = useState<Mode>('tcp')
  const [name, setName] = useState('')
  const [host, setHost] = useState('127.0.0.1')
  const [port, setPort] = useState(5020)
  // Modbus over serial line defaults: 19200 baud, 8 data bits, even parity, 1 stop bit.
  const [serialPort, setSerialPort] = useState('')
  const [baudrate, setBaudrate] = useState(19200)
  const [bytesize, setBytesize] = useState<RtuConnection['bytesize']>(8)
  const [parity, setParity] = useState<RtuConnection['parity']>('E')
  const [stopbits, setStopbits] = useState<RtuConnection['stopbits']>(1)
  const [timeoutMs, setTimeoutMs] = useState(1000)
  const [readOnly, setReadOnly] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    const common = {
      name: name.trim(),
      timeout_s: timeoutMs / 1000,
      retries: 0,
      delay_between_requests_ms: 0,
      read_only: readOnly,
    }
    try {
      const view = await api.createConnection(
        type === 'rtu'
          ? { ...common, type, serial_port: serialPort.trim(), baudrate, bytesize, parity, stopbits }
          : { ...common, type, host: host.trim(), port },
      )
      upsert(view)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal
      title="New connection"
      submitLabel="Create"
      busy={busy}
      error={error}
      onSubmit={submit}
      onClose={onClose}
    >
      <Field label="Mode">
        <select value={type} onChange={(e) => setType(e.target.value as Mode)}>
          <option value="tcp">Modbus TCP</option>
          <option value="rtu_over_tcp">RTU over TCP</option>
          <option value="rtu">Modbus RTU (serial port)</option>
        </select>
      </Field>
      <Field label="Name">
        <input value={name} placeholder="optional" onChange={(e) => setName(e.target.value)} />
      </Field>
      {type === 'rtu' ? (
        <>
          <SerialPortPicker value={serialPort} onChange={setSerialPort} />
          <div className="field-row">
            <Field label="Baud rate">
              <input
                type="number"
                min={1}
                list="baud-rates"
                value={baudrate}
                required
                onChange={(e) => setBaudrate(e.target.valueAsNumber)}
              />
              <datalist id="baud-rates">
                {BAUD_RATES.map((b) => (
                  <option key={b} value={b} />
                ))}
              </datalist>
            </Field>
            <Field label="Data bits">
              <select
                value={bytesize}
                onChange={(e) => setBytesize(Number(e.target.value) as RtuConnection['bytesize'])}
              >
                <option value={8}>8</option>
                <option value={7}>7</option>
              </select>
            </Field>
            <Field label="Parity">
              <select
                value={parity}
                onChange={(e) => setParity(e.target.value as RtuConnection['parity'])}
              >
                <option value="E">Even</option>
                <option value="O">Odd</option>
                <option value="N">None</option>
              </select>
            </Field>
            <Field label="Stop bits">
              <select
                value={stopbits}
                onChange={(e) => setStopbits(Number(e.target.value) as RtuConnection['stopbits'])}
              >
                <option value={1}>1</option>
                <option value={2}>2</option>
              </select>
            </Field>
          </div>
          <p className="hint">
            Every device on the line must use the same settings. The Modbus standard is 19200
            8E1; without parity it asks for 2 stop bits (8N2), though many devices use 8N1.
          </p>
        </>
      ) : (
        <>
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
        </>
      )}
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

/** Port name field plus the ports the server can see, to pick one with a click. */
function SerialPortPicker({
  value,
  onChange,
}: {
  value: string
  onChange: (port: string) => void
}) {
  const [ports, setPorts] = useState<SerialPort[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const show = (err: unknown) => setError(err instanceof Error ? err.message : String(err))

  useEffect(() => {
    let cancelled = false
    api
      .listSerialPorts()
      .then((found) => !cancelled && setPorts(found))
      .catch((err: unknown) => !cancelled && show(err))
    return () => {
      cancelled = true
    }
  }, [])

  const refresh = async () => {
    setError(null)
    try {
      setPorts(await api.listSerialPorts())
    } catch (err) {
      show(err)
    }
  }

  return (
    <>
      <Field label="Serial port">
        <input
          value={value}
          required
          placeholder="/dev/ttyUSB0, /dev/serial/by-id/…, COM3"
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
      <div className="port-list" aria-label="Serial ports found">
        <div className="port-list-head">
          <span>
            {ports === null
              ? 'Looking for serial ports…'
              : ports.length === 0
                ? 'No serial ports found on the server.'
                : 'Ports on the server (click to use):'}
          </span>
          <button type="button" className="btn btn-small" onClick={() => void refresh()}>
            Refresh
          </button>
        </div>
        {error && <p className="form-error">{error}</p>}
        {ports?.map((p) => {
          // The /dev/serial/by-id name survives replugging; prefer it when there is one.
          const path = p.stable_path ?? p.device
          return (
            <button
              type="button"
              key={p.device}
              className={`port${value === path || value === p.device ? ' chosen' : ''}`}
              onClick={() => onChange(path)}
            >
              <span className="mono">{p.device}</span>
              {p.description && <span> {p.description}</span>}
              {portDetails(p) && <small className="muted">{portDetails(p)}</small>}
              {p.stable_path && <small className="muted mono">{p.stable_path}</small>}
              {p.used_by.length > 0 && (
                <small className="warn">used by {p.used_by.join(', ')}</small>
              )}
            </button>
          )
        })}
        {ports?.length === 0 && (
          <p className="hint">
            In Docker, pass the adapter to the container, e.g.{' '}
            <code>--device /dev/ttyUSB0</code>. On Linux the user running modbus-studio needs
            the <code>dialout</code> group.
          </p>
        )}
      </div>
    </>
  )
}
