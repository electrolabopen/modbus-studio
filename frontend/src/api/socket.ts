import { useStudio } from '../store'
import { getToken } from './client'
import type { ServerMessage } from './types'

const MAX_BACKOFF_MS = 5000
const BASE_TOPICS = ['polls', 'connections', 'writes']

// Raw frames are only sent while someone looks at them (the traffic monitor).
let wantTraffic = false
let current: WebSocket | null = null

function sendTopics(socket: WebSocket) {
  const topics = wantTraffic ? [...BASE_TOPICS, 'traffic'] : BASE_TOPICS
  socket.send(JSON.stringify({ type: 'subscribe', topics }))
}

/** Start or stop receiving raw frames; survives reconnections. */
export function setTrafficSubscription(on: boolean): void {
  wantTraffic = on
  if (current?.readyState === WebSocket.OPEN) sendTopics(current)
}

/**
 * Keep a WebSocket to /api/ws open and feed its messages into the store.
 * Returns a function that closes it for good.
 */
export function connectSocket(): () => void {
  let socket: WebSocket | null = null
  let stopped = false
  let backoff = 250
  let timer: ReturnType<typeof setTimeout> | undefined

  const { setLink, handle } = useStudio.getState()

  const open = () => {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${scheme}://${location.host}/api/ws`)
    socket = current = ws
    setLink('connecting')

    ws.onopen = () => {
      const token = getToken()
      // The token goes in the first message, never in the URL.
      if (token) ws.send(JSON.stringify({ type: 'auth', token }))
      if (wantTraffic) sendTopics(ws)
    }
    ws.onmessage = (event) => {
      backoff = 250
      setLink('open')
      handle(JSON.parse(event.data as string) as ServerMessage)
    }
    ws.onclose = (event) => {
      socket = null
      if (current === ws) current = null
      if (stopped) return
      if (event.code === 1008) {
        setLink('unauthorized')
        return
      }
      setLink('closed')
      timer = setTimeout(open, backoff)
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS)
    }
  }

  open()
  return () => {
    stopped = true
    clearTimeout(timer)
    socket?.close()
  }
}
