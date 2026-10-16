import type {
  ConnectionConfig,
  ConnectionView,
  ExportersView,
  ExporterTest,
  FormatPatch,
  InfluxDBConfig,
  InfluxDBView,
  MQTTConfig,
  MQTTView,
  PollDefinition,
  PollView,
  SerialPort,
  WindowWrite,
  WriteLogEntry,
  Workspace,
  TrafficEntry,
  WritePlan,
} from './types'

export interface Health {
  status: string
  version: string
  auth: boolean
}

export class ApiError extends Error {
  readonly status: number
  /** Parsed JSON error body, when there was one (e.g. per-line CSV errors). */
  readonly body: unknown

  constructor(status: number, message: string, body: unknown = null) {
    super(message)
    this.status = status
    this.body = body
  }
}

const TOKEN_KEY = 'modbus-studio.token'

function readStoredToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

let token: string | null = readStoredToken()

export function getToken(): string | null {
  return token
}

/** Set the bearer token used when the server runs with MODBUS_STUDIO_TOKEN. */
export function setToken(value: string | null): void {
  token = value
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage unavailable: keep the token in memory only
  }
}

/** Turn FastAPI's error body (string or validation error list) into one message. */
function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object' || !('detail' in body)) return fallback
  const detail = (body as { detail: unknown }).detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((p) => p !== 'body').join('.')
        // Pydantic prefixes the messages of custom validators with "Value error, ".
        const msg = (d.msg ?? '').replace(/^Value error, /, '')
        return field ? `${field}: ${msg}` : msg
      })
      .join('; ')
  }
  return fallback
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  const res = await fetch(`/api${path}`, { ...init, headers })
  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, errorMessage(body, res.statusText), body)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  body: JSON.stringify(body),
})

export const getHealth = () => request<Health>('/health')

export const api = {
  createConnection: (config: ConnectionConfig) =>
    request<ConnectionView>('/connections', json('POST', config)),
  listSerialPorts: () => request<SerialPort[]>('/serial-ports'),
  updateConnection: (id: string, config: ConnectionConfig) =>
    request<ConnectionView>(`/connections/${encodeURIComponent(id)}`, json('PUT', config)),
  deleteConnection: (id: string, cascade = false) =>
    request<void>(`/connections/${encodeURIComponent(id)}?cascade=${cascade}`, {
      method: 'DELETE',
    }),
  createPoll: (definition: PollDefinition) =>
    request<PollView>('/polls', json('POST', definition)),
  updatePoll: (id: string, definition: PollDefinition) =>
    request<PollView>(`/polls/${encodeURIComponent(id)}`, json('PUT', definition)),
  deletePoll: (id: string) =>
    request<void>(`/polls/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  patchFormats: (id: string, patch: FormatPatch) =>
    request<PollView>(`/polls/${encodeURIComponent(id)}/formats`, json('PATCH', patch)),
  resetPoll: (id: string) =>
    request<PollView>(`/polls/${encodeURIComponent(id)}/reset`, { method: 'POST' }),
  previewWrite: (id: string, req: WindowWrite, signal?: AbortSignal) =>
    request<WritePlan>(`/polls/${encodeURIComponent(id)}/write/preview`, {
      ...json('POST', req),
      signal,
    }),
  /** With ``fit``, a window too small for the map grows to hold every row first. */
  importRegisterMap: (id: string, csv: string, fit = false) =>
    request<PollView>(
      `/polls/${encodeURIComponent(id)}/register-map${fit ? '?fit=true' : ''}`,
      json('POST', { csv }),
    ),
  exportWorkspace: () => request<Workspace>('/workspace'),
  importWorkspace: (workspace: Workspace, mode: 'replace' | 'merge') =>
    request<{ connections: number; polls: number }>(
      `/workspace?mode=${mode}`,
      json('POST', workspace),
    ),
  listTraffic: (limit = 1000) => request<TrafficEntry[]>(`/traffic?limit=${limit}`),
  clearTraffic: () => request<void>('/traffic', { method: 'DELETE' }),
  listWrites: (limit = 200) => request<WriteLogEntry[]>(`/writes?limit=${limit}`),
  write: (id: string, req: WindowWrite) =>
    request<WritePlan>(`/polls/${encodeURIComponent(id)}/write`, json('POST', req)),
  getExporters: () => request<ExportersView>('/exporters'),
  saveInfluxDB: (config: InfluxDBConfig) =>
    request<InfluxDBView>('/exporters/influxdb', json('PUT', config)),
  testInfluxDB: (config: InfluxDBConfig) =>
    request<ExporterTest>('/exporters/influxdb/test', json('POST', config)),
  saveMQTT: (config: MQTTConfig) => request<MQTTView>('/exporters/mqtt', json('PUT', config)),
  testMQTT: (config: MQTTConfig) =>
    request<ExporterTest>('/exporters/mqtt/test', json('POST', config)),
}
