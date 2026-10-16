// Status of the InfluxDB and MQTT exporters, shared by the toolbar and the dialog.
import { useEffect, useState } from 'react'
import { api } from './api/client'
import type { ExporterStatus, ExportersView } from './api/types'

export type ExporterKind = 'influxdb' | 'mqtt'

// The toolbar indicator, while the dialog is closed.
const BADGE_REFRESH_MS = 3000

export const STATE_LABELS: Record<ExporterKind, Record<ExporterStatus['state'], string>> = {
  influxdb: {
    disabled: 'Off',
    incomplete: 'Missing settings',
    idle: 'Waiting for the first write',
    ok: 'Writing',
    error: 'Failing',
  },
  mqtt: {
    disabled: 'Off',
    incomplete: 'Missing settings',
    idle: 'Connecting…',
    ok: 'Connected',
    error: 'Not connected',
  },
}

export function dotClass(status: ExporterStatus | undefined): string {
  switch (status?.state) {
    case 'ok':
      return 'dot dot-connected'
    case 'idle':
    case 'incomplete':
      return 'dot dot-connecting'
    case 'error':
      return 'dot dot-disconnected'
    default:
      return 'dot'
  }
}

/** The exporters' status, refreshed every few seconds while ``active``. */
export function useExporters(active: boolean): ExportersView | null {
  const [view, setView] = useState<ExportersView | null>(null)
  useEffect(() => {
    if (!active) return
    let stopped = false
    const load = () =>
      api
        .getExporters()
        .then((next) => !stopped && setView(next))
        .catch(() => {
          // the indicator just stays as it was; the dialog shows errors
        })
    void load()
    const timer = setInterval(() => void load(), BADGE_REFRESH_MS)
    return () => {
      stopped = true
      clearInterval(timer)
    }
  }, [active])
  return view
}

/** "InfluxDB: Writing · MQTT: Off", for the toolbar button's tooltip. */
export function exportersSummary(view: ExportersView | null): string {
  if (!view) return 'InfluxDB and MQTT exporters'
  const one = (kind: ExporterKind, name: string) =>
    `${name}: ${STATE_LABELS[kind][view[kind].status.state]}`
  return `${one('influxdb', 'InfluxDB')} · ${one('mqtt', 'MQTT')}`
}
