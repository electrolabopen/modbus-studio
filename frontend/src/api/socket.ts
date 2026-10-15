import { useStudio } from '../store'
import { getToken } from './client'
import type { ServerMessage } from './types'

const MAX_BACKOFF_MS = 5000

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
    socket = new WebSocket(`${scheme}://${location.host}/api/ws`)
    setLink('connecting')

    socket.onopen = () => {
      const token = getToken()
      // The token goes in the first message, never in the URL.
      if (token) socket?.send(JSON.stringify({ type: 'auth', token }))
    }
    socket.onmessage = (event) => {
      backoff = 250
      setLink('open')
      handle(JSON.parse(event.data as string) as ServerMessage)
    }
    socket.onclose = (event) => {
      socket = null
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
