import { useEffect, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type {
  ExporterStatus,
  ExportersView,
  ExporterTest,
  InfluxDBConfigView,
  InfluxDBSettings,
  MQTTConfigView,
  MQTTSettings,
} from '../api/types'
import { dotClass, STATE_LABELS, type ExporterKind } from '../exporters'
import { useStudio } from '../store'
import { clockTime } from '../util'
import { Field, Modal } from './Modal'

const STATUS_REFRESH_MS = 1000

const message = (err: unknown) => (err instanceof Error ? err.message : String(err))

/** A token or password being edited. It is only ever typed, never shown: the server
 * does not send it back, and the field starts empty. */
interface Secret {
  value: string
  remove: boolean
}

const NO_SECRET: Secret = { value: '', remove: false }

/** What to send for a secret: the new one, "" to remove it, or null to keep it. */
const secretPayload = (s: Secret): string | null => (s.value ? s.value : s.remove ? '' : null)

function influxSettings(c: InfluxDBConfigView): InfluxDBSettings {
  return {
    enabled: c.enabled,
    url: c.url,
    org: c.org,
    bucket: c.bucket,
    aliased_only: c.aliased_only,
    flush_interval_ms: c.flush_interval_ms,
    batch_size: c.batch_size,
    buffer_size: c.buffer_size,
    timeout_s: c.timeout_s,
    verify_tls: c.verify_tls,
  }
}

function mqttSettings(c: MQTTConfigView): MQTTSettings {
  return {
    enabled: c.enabled,
    host: c.host,
    port: c.port,
    client_id: c.client_id,
    username: c.username,
    topic: c.topic,
    qos: c.qos,
    retain: c.retain,
    aliased_only: c.aliased_only,
    keepalive_s: c.keepalive_s,
    buffer_size: c.buffer_size,
    tls: c.tls,
    ca_file: c.ca_file,
    cert_file: c.cert_file,
    key_file: c.key_file,
    verify_tls: c.verify_tls,
  }
}

const same = (a: object, b: object) => JSON.stringify(a) === JSON.stringify(b)

/** Settings, status and "Test connection" of the InfluxDB and MQTT exporters. */
export function ExportersDialog({
  onClose,
  initialTab = 'influxdb',
}: {
  onClose: () => void
  initialTab?: ExporterKind
}) {
  const [view, setView] = useState<ExportersView | null>(null)
  const [tab, setTab] = useState<ExporterKind>(initialTab)
  const [influx, setInflux] = useState<InfluxDBSettings | null>(null)
  const [mqtt, setMqtt] = useState<MQTTSettings | null>(null)
  const [token, setToken] = useState<Secret>(NO_SECRET)
  const [password, setPassword] = useState<Secret>(NO_SECRET)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [test, setTest] = useState<{ kind: ExporterKind; result: ExporterTest } | null>(null)
  const [testing, setTesting] = useState(false)

  // Settings are read once; the status is refreshed while the dialog is open.
  useEffect(() => {
    let stopped = false
    const load = async () => {
      try {
        const next = await api.getExporters()
        if (stopped) return
        setView(next)
        setInflux((form) => form ?? influxSettings(next.influxdb.config))
        setMqtt((form) => form ?? mqttSettings(next.mqtt.config))
      } catch (err) {
        if (!stopped) setError(message(err))
      }
    }
    void load()
    const timer = setInterval(() => void load(), STATUS_REFRESH_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [])

  /** Wrap a setter so that editing the form clears the last test result and notice. */
  const edits =
    <T,>(setter: (value: T) => void) =>
    (value: T) => {
      setTest(null)
      setNotice(null)
      setter(value)
    }

  const influxPayload = (form: InfluxDBSettings) => ({ ...form, token: secretPayload(token) })
  const mqttPayload = (form: MQTTSettings) => ({ ...form, password: secretPayload(password) })

  const save = async () => {
    setBusy(true)
    setError(null)
    setNotice(null)
    setTest(null)
    try {
      if (tab === 'influxdb' && influx) {
        const saved = await api.saveInfluxDB(influxPayload(influx))
        setView((v) => v && { ...v, influxdb: saved })
        setInflux(influxSettings(saved.config))
        setToken(NO_SECRET)
      } else if (tab === 'mqtt' && mqtt) {
        const saved = await api.saveMQTT(mqttPayload(mqtt))
        setView((v) => v && { ...v, mqtt: saved })
        setMqtt(mqttSettings(saved.config))
        setPassword(NO_SECRET)
      }
      setNotice('Saved and applied.')
    } catch (err) {
      setError(message(err))
    } finally {
      setBusy(false)
    }
  }

  /** Try the settings as they are in the form, without saving them. */
  const runTest = async () => {
    const kind = tab
    setTesting(true)
    setError(null)
    setTest(null)
    try {
      let result: ExporterTest | null = null
      if (kind === 'influxdb' && influx) result = await api.testInfluxDB(influxPayload(influx))
      if (kind === 'mqtt' && mqtt) result = await api.testMQTT(mqttPayload(mqtt))
      if (result) setTest({ kind, result })
    } catch (err) {
      setError(message(err))
    } finally {
      setTesting(false)
    }
  }

  const current = view?.[tab]
  const secretEdited = (s: Secret) => s.value !== '' || s.remove
  let dirty = false
  if (view && tab === 'influxdb' && influx) {
    dirty = !same(influx, influxSettings(view.influxdb.config)) || secretEdited(token)
  }
  if (view && tab === 'mqtt' && mqtt) {
    dirty = !same(mqtt, mqttSettings(view.mqtt.config)) || secretEdited(password)
  }

  return (
    <Modal
      title="Exporters"
      submitLabel="Save"
      cancelLabel="Close"
      className="modal-wide"
      busy={busy || !view}
      error={error}
      onSubmit={() => void save()}
      onClose={onClose}
      secondary={{
        label: testing ? 'Testing…' : 'Test connection',
        onClick: () => void runTest(),
        disabled: testing || !view,
      }}
    >
      <div className="tabs" role="tablist">
        {(['influxdb', 'mqtt'] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            role="tab"
            aria-selected={tab === kind}
            className={`tab${tab === kind ? ' active' : ''}`}
            onClick={() => {
              setTab(kind)
              setNotice(null)
              setError(null)
            }}
          >
            <StatusDot status={view?.[kind].status} />
            {kind === 'influxdb' ? 'InfluxDB' : 'MQTT'}
          </button>
        ))}
      </div>
      {current ? (
        <StatusBox kind={tab} status={current.status} />
      ) : (
        <p className="hint">Loading…</p>
      )}
      {tab === 'influxdb' && influx && view && (
        <InfluxForm
          form={influx}
          onChange={edits(setInflux)}
          token={token}
          onToken={edits(setToken)}
          tokenSet={view.influxdb.config.token_set}
        />
      )}
      {tab === 'mqtt' && mqtt && view && (
        <MqttForm
          form={mqtt}
          onChange={edits(setMqtt)}
          password={password}
          onPassword={edits(setPassword)}
          passwordSet={view.mqtt.config.password_set}
        />
      )}
      {test?.kind === tab && (
        <p className={test.result.ok ? 'test-ok' : 'test-failed'} role="status">
          {test.result.ok ? '✓ ' : '✗ '}
          {test.result.message}{' '}
          <span className="muted">({Math.round(test.result.elapsed_ms)} ms)</span>
        </p>
      )}
      {dirty ? (
        <p className="form-note">
          Unsaved changes: the status above is for the saved settings. Test connection tries
          these ones without saving them.
        </p>
      ) : (
        notice && <p className="test-ok">{notice}</p>
      )}
    </Modal>
  )
}

export function StatusDot({ status }: { status: ExporterStatus | undefined }) {
  return <span className={dotClass(status)} aria-hidden="true" />
}

function StatusBox({ kind, status }: { kind: ExporterKind; status: ExporterStatus }) {
  const unit = kind === 'influxdb' ? 'points' : 'messages'
  return (
    <div className="exporter-status" aria-label="Status">
      <div className="exporter-state">
        <StatusDot status={status} />
        <strong>{STATE_LABELS[kind][status.state]}</strong>
        {status.last_success_at !== null && (
          <span className="muted small">
            last {kind === 'influxdb' ? 'write' : 'message'} {clockTime(status.last_success_at)}
          </span>
        )}
      </div>
      <dl className="counters">
        <Counter label={`${unit} sent`} value={status.points_sent} />
        {kind === 'influxdb' && <Counter label="writes" value={status.writes} />}
        <Counter label="errors" value={status.errors} warn={status.errors > 0} />
        <Counter label="dropped" value={status.dropped} warn={status.dropped > 0} />
        <Counter label="pending" value={status.pending} />
      </dl>
      {status.last_error && (
        <p className={status.state === 'error' ? 'conn-error small' : 'muted small'}>
          {status.state === 'error' ? 'Error' : 'Last error'}
          {status.last_error_at !== null && ` at ${clockTime(status.last_error_at)}`}:{' '}
          {status.last_error}
        </p>
      )}
    </div>
  )
}

function Counter({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className={warn ? 'counter warn' : 'counter'}>
      <dt>{label}</dt>
      <dd>{value.toLocaleString()}</dd>
    </div>
  )
}

/** A token or password field: typed, never displayed. */
function SecretField({
  label,
  secret,
  onChange,
  isSet,
  hint,
}: {
  label: string
  secret: Secret
  onChange: (s: Secret) => void
  isSet: boolean
  hint: string
}) {
  return (
    <>
      <Field label={label}>
        <input
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={secret.value}
          placeholder={isSet ? 'saved (hidden): type a new one to replace it' : hint}
          onChange={(e) => onChange({ value: e.target.value, remove: false })}
        />
      </Field>
      {isSet && (
        <label className="check">
          <input
            type="checkbox"
            checked={secret.remove}
            disabled={!!secret.value}
            onChange={(e) => onChange({ value: '', remove: e.target.checked })}
          />
          Remove the saved {label.toLowerCase()}
        </label>
      )}
    </>
  )
}

function Check({
  checked,
  onChange,
  children,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  children: ReactNode
}) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  )
}

function InfluxForm({
  form,
  onChange,
  token,
  onToken,
  tokenSet,
}: {
  form: InfluxDBSettings
  onChange: (form: InfluxDBSettings) => void
  token: Secret
  onToken: (s: Secret) => void
  tokenSet: boolean
}) {
  const set = <K extends keyof InfluxDBSettings>(key: K, value: InfluxDBSettings[K]) =>
    onChange({ ...form, [key]: value })
  return (
    <>
      <Check checked={form.enabled} onChange={(v) => set('enabled', v)}>
        Write every polled value to InfluxDB 2.x
      </Check>
      <Field label="URL">
        <input
          value={form.url}
          required
          placeholder="http://influxdb:8086"
          onChange={(e) => set('url', e.target.value)}
        />
      </Field>
      <div className="field-row">
        <Field label="Organization">
          <input value={form.org} onChange={(e) => set('org', e.target.value)} />
        </Field>
        <Field label="Bucket">
          <input value={form.bucket} onChange={(e) => set('bucket', e.target.value)} />
        </Field>
      </div>
      <SecretField
        label="Token"
        secret={token}
        onChange={onToken}
        isSet={tokenSet}
        hint="an API token with write access to the bucket"
      />
      <Check checked={form.aliased_only} onChange={(v) => set('aliased_only', v)}>
        Only registers with an alias
      </Check>
      <details className="advanced">
        <summary>Advanced</summary>
        <div className="field-row">
          <Field label="Write every (ms)">
            <input
              type="number"
              min={100}
              max={60000}
              value={form.flush_interval_ms}
              onChange={(e) => set('flush_interval_ms', e.target.valueAsNumber)}
            />
          </Field>
          <Field label="Points per write">
            <input
              type="number"
              min={1}
              max={50000}
              value={form.batch_size}
              onChange={(e) => set('batch_size', e.target.valueAsNumber)}
            />
          </Field>
        </div>
        <div className="field-row">
          <Field label="Buffer while offline (points)">
            <input
              type="number"
              min={100}
              value={form.buffer_size}
              onChange={(e) => set('buffer_size', e.target.valueAsNumber)}
            />
          </Field>
          <Field label="Timeout (s)">
            <input
              type="number"
              min={0.1}
              max={60}
              step={0.1}
              value={form.timeout_s}
              onChange={(e) => set('timeout_s', e.target.valueAsNumber)}
            />
          </Field>
        </div>
        <Check checked={form.verify_tls} onChange={(v) => set('verify_tls', v)}>
          Verify the server certificate (https)
        </Check>
      </details>
    </>
  )
}

const TOPIC_FIELDS = ['connection', 'device', 'window', 'alias', 'address', 'unit'] as const

/** The topic a value would get, with the first window of the session as the example. */
function useTopicExample(template: string): string {
  const polls = useStudio((s) => s.polls)
  const connections = useStudio((s) => s.connections)
  const poll = Object.values(polls)[0]
  const conn = poll && connections[poll.definition.connection_id]
  const values: Record<(typeof TOPIC_FIELDS)[number], string> = {
    connection: conn?.config.name || conn?.config.id || 'plc1',
    device: String(poll?.definition.device_id ?? 1),
    window: poll?.definition.name || poll?.definition.id || 'Window',
    alias: 'temperature',
    address: '2',
    unit: '°C',
  }
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in values ? values[name as keyof typeof values].replace(/[/+#]/g, '_') : whole,
  )
}

function MqttForm({
  form,
  onChange,
  password,
  onPassword,
  passwordSet,
}: {
  form: MQTTSettings
  onChange: (form: MQTTSettings) => void
  password: Secret
  onPassword: (s: Secret) => void
  passwordSet: boolean
}) {
  const set = <K extends keyof MQTTSettings>(key: K, value: MQTTSettings[K]) =>
    onChange({ ...form, [key]: value })
  const example = useTopicExample(form.topic)
  return (
    <>
      <Check checked={form.enabled} onChange={(v) => set('enabled', v)}>
        Publish every polled value to an MQTT broker
      </Check>
      <div className="field-row">
        <Field label="Broker host">
          <input
            value={form.host}
            required
            placeholder="mosquitto"
            onChange={(e) => set('host', e.target.value)}
          />
        </Field>
        <Field label="Port">
          <input
            type="number"
            min={1}
            max={65535}
            value={form.port}
            required
            onChange={(e) => set('port', e.target.valueAsNumber)}
          />
        </Field>
      </div>
      <div className="field-row">
        <Field label="User name">
          <input
            value={form.username}
            autoComplete="off"
            placeholder="empty: anonymous"
            onChange={(e) => set('username', e.target.value)}
          />
        </Field>
      </div>
      <SecretField
        label="Password"
        secret={password}
        onChange={onPassword}
        isSet={passwordSet}
        hint="the broker account's password"
      />
      <Field label="Topic">
        <input
          value={form.topic}
          required
          spellCheck={false}
          className="mono"
          onChange={(e) => set('topic', e.target.value)}
        />
      </Field>
      <p className="hint">
        Placeholders: {TOPIC_FIELDS.map((f) => `{${f}}`).join(' ')}. For example:{' '}
        <code>{example}</code>
      </p>
      <div className="field-row">
        <Field label="QoS">
          <select
            value={form.qos}
            onChange={(e) => set('qos', Number(e.target.value) as MQTTSettings['qos'])}
          >
            <option value={0}>0: at most once</option>
            <option value={1}>1: at least once</option>
            <option value={2}>2: exactly once</option>
          </select>
        </Field>
      </div>
      <Check checked={form.retain} onChange={(v) => set('retain', v)}>
        Retain: the broker keeps the last value of each topic for new subscribers
      </Check>
      <Check checked={form.aliased_only} onChange={(v) => set('aliased_only', v)}>
        Only registers with an alias
      </Check>
      <Check checked={form.tls} onChange={(v) => set('tls', v)}>
        TLS (usually port 8883)
      </Check>
      {form.tls && (
        <div className="indent">
          <Field label="CA certificate (PEM file on the server)">
            <input
              value={form.ca_file}
              placeholder="empty: the system's CA certificates"
              onChange={(e) => set('ca_file', e.target.value)}
            />
          </Field>
          <div className="field-row">
            <Field label="Client certificate">
              <input
                value={form.cert_file}
                placeholder="optional"
                onChange={(e) => set('cert_file', e.target.value)}
              />
            </Field>
            <Field label="Client key">
              <input
                value={form.key_file}
                placeholder="optional"
                onChange={(e) => set('key_file', e.target.value)}
              />
            </Field>
          </div>
          <Check checked={form.verify_tls} onChange={(v) => set('verify_tls', v)}>
            Verify the broker's certificate and host name
          </Check>
        </div>
      )}
      <details className="advanced">
        <summary>Advanced</summary>
        <div className="field-row">
          <Field label="Client ID">
            <input
              value={form.client_id}
              placeholder="empty: modbus-studio-<random>"
              onChange={(e) => set('client_id', e.target.value)}
            />
          </Field>
          <Field label="Keepalive (s)">
            <input
              type="number"
              min={5}
              max={3600}
              value={form.keepalive_s}
              onChange={(e) => set('keepalive_s', e.target.valueAsNumber)}
            />
          </Field>
        </div>
        <Field label="Buffer while offline (messages)">
          <input
            type="number"
            min={100}
            value={form.buffer_size}
            onChange={(e) => set('buffer_size', e.target.valueAsNumber)}
          />
        </Field>
      </details>
    </>
  )
}
