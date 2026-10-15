import { create } from 'zustand'
import {
  MAX_SERIES,
  appendSample,
  sameSeries,
  sampleOf,
  seriesId,
  type Sample,
  type SeriesKey,
} from './chart'
import type {
  Cell,
  ConnectionView,
  PollData,
  PollView,
  ServerMessage,
  TrafficEntry,
  WriteLogEntry,
} from './api/types'

const MAX_WRITES = 200
/** Frames kept in the browser; matches the server's default traffic buffer. */
export const MAX_FRAMES = 5000

export type LinkState = 'connecting' | 'open' | 'closed' | 'unauthorized'

const PLOTTED_KEY = 'modbus-studio.plotted'

/** The plotted series are a per-browser preference, not part of the workspace. */
function loadPlotted(): SeriesKey[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(PLOTTED_KEY) ?? '[]')
    if (!Array.isArray(saved)) return []
    return saved
      .filter(
        (k): k is SeriesKey =>
          typeof k?.poll === 'string' && Number.isInteger(k?.address),
      )
      .slice(0, MAX_SERIES)
  } catch {
    return []
  }
}

function savePlotted(plotted: SeriesKey[]): void {
  try {
    localStorage.setItem(PLOTTED_KEY, JSON.stringify(plotted))
  } catch {
    // Storage blocked or full: the chart just starts empty next time.
  }
}

interface StudioState {
  link: LinkState
  connections: Record<string, ConnectionView>
  polls: Record<string, PollView>
  /** Last successfully read cells per window, kept while reads fail. */
  cells: Record<string, Cell[]>
  /** Latest result per window, successful or not. */
  latest: Record<string, PollData>
  /** Write log, newest first. */
  writes: WriteLogEntry[]
  setWrites: (entries: WriteLogEntry[]) => void
  /** Raw frames received while the traffic monitor is open, oldest first. */
  traffic: TrafficEntry[]
  setTraffic: (entries: TrafficEntry[]) => void
  /** Values on the chart, in legend order. */
  plotted: SeriesKey[]
  /**
   * Samples per plotted series (by seriesId). The buffers grow in place; the
   * record itself is replaced on every change so that subscribers re-render.
   */
  history: Record<string, Sample[]>
  /** Values selected in each window (first address of each value), for the chart's hint. */
  selected: Record<string, number[]>
  setSelected: (poll: string, addresses: number[]) => void
  /** Add series (up to MAX_SERIES); returns how many did not fit. */
  plot: (keys: SeriesKey[]) => number
  unplot: (keys: SeriesKey[]) => void
  clearHistory: () => void
  setLink: (link: LinkState) => void
  handle: (message: ServerMessage) => void
  upsertPoll: (view: PollView) => void
  upsertConnection: (view: ConnectionView) => void
}

export const useStudio = create<StudioState>()((set, get) => ({
  link: 'connecting',
  connections: {},
  polls: {},
  cells: {},
  latest: {},
  writes: [],
  setWrites: (entries) => set({ writes: entries.slice(0, MAX_WRITES) }),
  traffic: [],
  setTraffic: (entries) => set({ traffic: entries.slice(-MAX_FRAMES) }),
  plotted: loadPlotted(),
  history: {},
  selected: {},
  setSelected: (poll, addresses) =>
    set((s) => {
      if (addresses.length === 0) {
        if (!(poll in s.selected)) return {}
        const selected = { ...s.selected }
        delete selected[poll]
        return { selected }
      }
      return { selected: { ...s.selected, [poll]: addresses } }
    }),
  plot: (keys) => {
    const s = get()
    const fresh = keys.filter(
      (k, i) =>
        !s.plotted.some((p) => sameSeries(p, k)) &&
        keys.findIndex((x) => sameSeries(x, k)) === i,
    )
    const added = fresh.slice(0, Math.max(0, MAX_SERIES - s.plotted.length))
    if (added.length > 0) {
      const plotted = [...s.plotted, ...added]
      const history = { ...s.history }
      for (const k of added) {
        // Start from the value on screen instead of an empty line.
        const data = s.latest[k.poll]
        history[seriesId(k)] = data?.ok ? [sampleOf(data, k.address)] : []
      }
      set({ plotted, history })
      savePlotted(plotted)
    }
    return fresh.length - added.length
  },
  unplot: (keys) => {
    const s = get()
    const plotted = s.plotted.filter((p) => !keys.some((k) => sameSeries(p, k)))
    if (plotted.length === s.plotted.length) return
    const history = { ...s.history }
    for (const k of keys) delete history[seriesId(k)]
    set({ plotted, history })
    savePlotted(plotted)
  },
  clearHistory: () => set({ history: {} }),
  setLink: (link) => set({ link }),
  upsertPoll: (view) =>
    set((s) => ({ polls: { ...s.polls, [view.definition.id]: view } })),
  upsertConnection: (view) =>
    set((s) => ({ connections: { ...s.connections, [view.config.id]: view } })),
  handle: (message) =>
    set((s) => {
      switch (message.type) {
        case 'snapshot': {
          const polls: Record<string, PollView> = {}
          const cells: Record<string, Cell[]> = {}
          const latest: Record<string, PollData> = {}
          for (const p of message.polls) {
            const id = p.definition.id
            polls[id] = p
            // Keep the cells we already have when the snapshot has none yet.
            const fresh = p.data?.ok ? p.data.cells : undefined
            const kept = fresh ?? s.cells[id]
            if (kept) cells[id] = kept
            const data = p.data ?? s.latest[id]
            if (data) latest[id] = data
          }
          const connections = Object.fromEntries(
            message.connections.map((c) => [c.config.id, c]),
          )
          // A window that is gone takes its series off the chart.
          const plotted = s.plotted.filter((k) => polls[k.poll])
          if (plotted.length === s.plotted.length) return { polls, cells, latest, connections }
          savePlotted(plotted)
          return { polls, cells, latest, connections, plotted }
        }
        case 'poll': {
          const data = message.data
          const id = data.poll_id
          if (!s.polls[id]) return {}
          const latest = { ...s.latest, [id]: data }
          const update: Partial<StudioState> = { latest }
          if (data.ok) update.cells = { ...s.cells, [id]: data.cells }
          const keys = s.plotted.filter((k) => k.poll === id)
          if (keys.length > 0) {
            const history = { ...s.history }
            for (const k of keys) {
              const buffer = (history[seriesId(k)] ??= [])
              appendSample(buffer, sampleOf(data, k.address))
            }
            update.history = history
          }
          return update
        }
        case 'connection':
          return { connections: { ...s.connections, [message.data.config.id]: message.data } }
        case 'traffic': {
          const last = s.traffic[s.traffic.length - 1]
          if (last && message.data.seq === last.seq) return {}
          // Sequence numbers restart with the server: start a new list.
          if (last && message.data.seq < last.seq) return { traffic: [message.data] }
          const traffic = [...s.traffic, message.data]
          return { traffic: traffic.length > MAX_FRAMES ? traffic.slice(-MAX_FRAMES) : traffic }
        }
        case 'write':
          if (s.writes.some((w) => w.seq === message.data.seq)) return {}
          return { writes: [message.data, ...s.writes].slice(0, MAX_WRITES) }
        default:
          return {}
      }
    }),
}))
