import { create } from 'zustand'
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
  setLink: (link: LinkState) => void
  handle: (message: ServerMessage) => void
  upsertPoll: (view: PollView) => void
  upsertConnection: (view: ConnectionView) => void
}

export const useStudio = create<StudioState>()((set) => ({
  link: 'connecting',
  connections: {},
  polls: {},
  cells: {},
  latest: {},
  writes: [],
  setWrites: (entries) => set({ writes: entries.slice(0, MAX_WRITES) }),
  traffic: [],
  setTraffic: (entries) => set({ traffic: entries.slice(-MAX_FRAMES) }),
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
          return { polls, cells, latest, connections }
        }
        case 'poll': {
          const id = message.data.poll_id
          if (!s.polls[id]) return {}
          const latest = { ...s.latest, [id]: message.data }
          if (!message.data.ok) return { latest }
          return { latest, cells: { ...s.cells, [id]: message.data.cells } }
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
