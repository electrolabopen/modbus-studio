// Mirrors backend/src/modbus_studio/models. Keep in sync with the OpenAPI schema.

export type DataType =
  | 'int16'
  | 'uint16'
  | 'hex16'
  | 'bin16'
  | 'int32'
  | 'uint32'
  | 'float32'
  | 'int64'
  | 'uint64'
  | 'float64'

export type ByteOrder = 'ABCD' | 'CDAB' | 'BADC' | 'DCBA'

export interface RegisterFormat {
  dtype: DataType
  order: ByteOrder
  scale: number
  unit: string
  alias: string
}

interface ConnectionBase {
  id?: string
  name: string
  timeout_s: number
  retries: number
  delay_between_requests_ms: number
  /** Block every write on this connection. */
  read_only?: boolean
}

export interface TcpConnection extends ConnectionBase {
  type: 'tcp' | 'rtu_over_tcp'
  host: string
  port: number
}

export interface RtuConnection extends ConnectionBase {
  type: 'rtu'
  serial_port: string
  baudrate: number
  bytesize: 7 | 8
  parity: 'N' | 'E' | 'O'
  stopbits: 1 | 2
}

export type ConnectionConfig = TcpConnection | RtuConnection

export type ConnectionState = 'disconnected' | 'connecting' | 'connected'

export interface ConnectionView {
  config: ConnectionConfig & { id: string }
  state: ConnectionState
  stats: Record<string, number>
  last_error?: string | null
}

export type ReadFunction = 1 | 2 | 3 | 4

export interface PollDefinition {
  id?: string
  connection_id: string
  name: string
  device_id: number
  function: ReadFunction
  address: number
  quantity: number
  scan_rate_ms: number
  enabled: boolean
  default_format: RegisterFormat
  formats: Record<string, RegisterFormat>
}

export interface PollStats {
  polls: number
  valid: number
  timeouts: number
  exceptions: number
  invalid: number
  disconnected: number
  errors: number
}

export interface Cell {
  address: number
  value: number | boolean | null
  text: string
  raw: number[]
  alias: string
  unit: string
  covered_by: number | null
  error: string | null
}

export interface PollData {
  poll_id: string
  seq: number
  timestamp: number
  duration_ms: number
  ok: boolean
  error_kind: 'timeout' | 'exception' | 'disconnected' | 'invalid' | null
  error: string | null
  exception_code: number | null
  stats: PollStats
  cells: Cell[]
}

export interface PollView {
  definition: PollDefinition & { id: string }
  running: boolean
  stats: PollStats
  data: PollData | null
}

export type ServerMessage =
  | { type: 'snapshot'; connections: ConnectionView[]; polls: PollView[] }
  | { type: 'poll'; data: PollData }
  | { type: 'connection'; data: ConnectionView }
  | { type: 'traffic'; data: TrafficEntry }
  | { type: 'write'; data: WriteLogEntry }

/** One captured frame. Header fields are null when the frame is too short to tell. */
export interface TrafficEntry {
  seq: number
  /** Unix time in seconds. */
  timestamp: number
  connection_id: string
  direction: 'tx' | 'rx'
  /** Bytes as upper-case hex pairs separated by spaces. */
  hex: string
  device_id: number | null
  function: number | null
  exception_code: number | null
  transaction_id: number | null
  /** Problem with the frame itself: bad CRC, wrong MBAP length, too short. */
  error: string | null
}

/** A serial port of the machine running the server. */
export interface SerialPort {
  device: string
  description: string
  manufacturer: string | null
  serial_number: string | null
  vid: number | null
  pid: number | null
  /** /dev/serial/by-id/... (Linux, USB): keeps working when adapters are replugged. */
  stable_path: string | null
  /** Ids of the connections configured with this port. */
  used_by: string[]
}

/** Connections and windows of a session, as exported to / imported from JSON. */
export interface Workspace {
  version: 1
  connections: (ConnectionConfig & { id: string })[]
  polls: PollDefinition[]
}

/** One problem in a CSV register map, as reported by the server. */
export interface MapError {
  line: number
  message: string
}

/** One write sent (or attempted) to a device. */
export interface WriteLogEntry {
  seq: number
  /** Unix time in seconds. */
  timestamp: number
  connection_id: string
  connection_name: string
  device_id: number
  function: 5 | 6 | 15 | 16
  address: number
  poll_id: string | null
  alias: string
  unit: string
  /** Value the window showed before the write; null when unknown. */
  old: string | null
  new: string
  values: number[]
  ok: boolean
  error: string | null
}

/** Display settings for cells start..end; omitted fields keep each cell's value. */
export interface FormatPatch {
  start: number
  end: number
  dtype?: DataType
  order?: ByteOrder
  scale?: number
  unit?: string
  alias?: string
  reset?: boolean
}

export interface WindowWrite {
  address: number
  value: boolean | number
  force_multiple?: boolean
}

/** What a window write sends, returned by the preview and write endpoints. */
export interface WritePlan {
  poll_id: string
  connection_id: string
  device_id: number
  function: 5 | 6 | 15 | 16
  address: number
  /** Coil states (0/1) or registers in wire order, exactly as sent. */
  values: number[]
  requested: boolean | number
  result: boolean | number
  text: string
  rounded: boolean
  unit: string
  dtype: DataType | null
  order: ByteOrder | null
  scale: number | null
}

export const WRITE_FUNCTION_LABELS: Record<WritePlan['function'], string> = {
  5: '05 Write Single Coil',
  6: '06 Write Single Register',
  15: '15 Write Multiple Coils',
  16: '16 Write Multiple Registers',
}

export const FUNCTION_LABELS: Record<ReadFunction, string> = {
  1: '01 Read Coils',
  2: '02 Read Discrete Inputs',
  3: '03 Read Holding Registers',
  4: '04 Read Input Registers',
}

export const DATA_TYPES: { value: DataType; label: string }[] = [
  { value: 'int16', label: 'Signed' },
  { value: 'uint16', label: 'Unsigned' },
  { value: 'hex16', label: 'Hex' },
  { value: 'bin16', label: 'Binary' },
  { value: 'int32', label: '32-bit signed' },
  { value: 'uint32', label: '32-bit unsigned' },
  { value: 'float32', label: '32-bit float' },
  { value: 'int64', label: '64-bit signed' },
  { value: 'uint64', label: '64-bit unsigned' },
  { value: 'float64', label: '64-bit double' },
]

export const BYTE_ORDERS: ByteOrder[] = ['ABCD', 'CDAB', 'BADC', 'DCBA']

export const DEFAULT_FORMAT: RegisterFormat = {
  dtype: 'int16',
  order: 'ABCD',
  scale: 1,
  unit: '',
  alias: '',
}

// -- exporters (InfluxDB, MQTT) -------------------------------------------------

export type ExporterState = 'disabled' | 'incomplete' | 'idle' | 'ok' | 'error'

export interface ExporterStatus {
  state: ExporterState
  last_error: string | null
  last_error_at: number | null
  last_success_at: number | null
  points_sent: number
  /** InfluxDB: write requests. MQTT: messages, one per value. */
  writes: number
  errors: number
  dropped: number
  pending: number
  /** MQTT only. */
  connected: boolean | null
}

export interface InfluxDBSettings {
  enabled: boolean
  url: string
  org: string
  bucket: string
  aliased_only: boolean
  flush_interval_ms: number
  batch_size: number
  buffer_size: number
  timeout_s: number
  verify_tls: boolean
}

/** Sent to the server. ``token``: omitted or null keeps the saved one, "" removes it. */
export interface InfluxDBConfig extends InfluxDBSettings {
  token?: string | null
}

/** Returned by the server: never the token itself. */
export interface InfluxDBConfigView extends InfluxDBSettings {
  token_set: boolean
}

export interface MQTTSettings {
  enabled: boolean
  host: string
  port: number
  client_id: string
  username: string
  topic: string
  qos: 0 | 1 | 2
  retain: boolean
  aliased_only: boolean
  keepalive_s: number
  buffer_size: number
  tls: boolean
  ca_file: string
  cert_file: string
  key_file: string
  verify_tls: boolean
}

/** Sent to the server. ``password``: omitted or null keeps the saved one, "" removes it. */
export interface MQTTConfig extends MQTTSettings {
  password?: string | null
}

/** Returned by the server: never the password itself. */
export interface MQTTConfigView extends MQTTSettings {
  password_set: boolean
}

export interface InfluxDBView {
  config: InfluxDBConfigView
  status: ExporterStatus
}

export interface MQTTView {
  config: MQTTConfigView
  status: ExporterStatus
}

export interface ExportersView {
  influxdb: InfluxDBView
  mqtt: MQTTView
}

/** The result of "Test connection": the settings are tried, not saved. */
export interface ExporterTest {
  ok: boolean
  message: string
  elapsed_ms: number
}
