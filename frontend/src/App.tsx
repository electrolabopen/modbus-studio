import { useEffect, useState } from 'react'
import { getHealth, getToken, setToken, type Health } from './api/client'
import { connectSocket } from './api/socket'
import { ConnectionDialog } from './components/ConnectionDialog'
import { Field, Modal } from './components/Modal'
import { PollDialog } from './components/PollDialog'
import { PollWindow } from './components/PollWindow'
import { Sidebar } from './components/Sidebar'
import { useStudio, type LinkState } from './store'
import './App.css'

type BackendState =
  | { kind: 'loading' }
  | { kind: 'online'; health: Health }
  | { kind: 'offline'; error: string }

export default function App() {
  const [backend, setBackend] = useState<BackendState>({ kind: 'loading' })
  const [tokenNeeded, setTokenNeeded] = useState(false)
  const [linkKey, setLinkKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    getHealth()
      .then((health) => {
        if (cancelled) return
        setBackend({ kind: 'online', health })
        if (health.auth && !getToken()) setTokenNeeded(true)
      })
      .catch((err: unknown) => {
        if (!cancelled) setBackend({ kind: 'offline', error: String(err) })
      })
    return () => {
      cancelled = true
    }
  }, [])

  const link = useStudio((s) => s.link)
  const askToken = tokenNeeded || link === 'unauthorized'
  const online = backend.kind === 'online'
  useEffect(() => {
    if (!online || askToken) return
    return connectSocket()
  }, [online, askToken, linkKey])

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">modbus-studio</span>
        <Toolbar enabled={online && link === 'open'} />
        <div className="topbar-right">
          <LinkBadge backend={backend} link={link} />
        </div>
      </header>
      <div className="main">
        <Sidebar />
        <Workspace />
      </div>
      {askToken && (
        <TokenDialog
          onDone={() => {
            useStudio.getState().setLink('connecting')
            setTokenNeeded(false)
            setLinkKey((k) => k + 1)
          }}
        />
      )}
    </div>
  )
}

function Toolbar({ enabled }: { enabled: boolean }) {
  const hasConnections = useStudio((s) => Object.keys(s.connections).length > 0)
  const [dialog, setDialog] = useState<'connection' | 'poll' | null>(null)
  return (
    <div className="toolbar">
      <button className="btn" disabled={!enabled} onClick={() => setDialog('connection')}>
        + Connection
      </button>
      <button
        className="btn"
        disabled={!enabled || !hasConnections}
        title={hasConnections ? undefined : 'Create a connection first'}
        onClick={() => setDialog('poll')}
      >
        + Window
      </button>
      {dialog === 'connection' && <ConnectionDialog onClose={() => setDialog(null)} />}
      {dialog === 'poll' && <PollDialog onClose={() => setDialog(null)} />}
    </div>
  )
}

function Workspace() {
  const polls = useStudio((s) => s.polls)
  const list = Object.values(polls)
  if (list.length === 0) {
    return (
      <main className="workspace workspace-empty">
        <div className="empty">
          <p>No polling windows yet.</p>
          <p className="muted">Create a connection, then a window to start polling.</p>
        </div>
      </main>
    )
  }
  return (
    <main className="workspace">
      {list.map((view) => (
        <PollWindow key={view.definition.id} view={view} />
      ))}
    </main>
  )
}

function LinkBadge({ backend, link }: { backend: BackendState; link: LinkState }) {
  if (backend.kind === 'loading') return <span className="badge">connecting…</span>
  if (backend.kind === 'offline')
    return (
      <span className="badge badge-danger" title={backend.error}>
        backend offline
      </span>
    )
  const live = link === 'open'
  return (
    <span className={`badge ${live ? 'badge-ok' : 'badge-danger'}`}>
      backend v{backend.health.version}
      {live ? '' : ` · ${link}`}
    </span>
  )
}

function TokenDialog({ onDone }: { onDone: () => void }) {
  const [value, setValue] = useState('')
  return (
    <Modal
      title="Access token"
      submitLabel="Connect"
      onSubmit={() => {
        setToken(value.trim() || null)
        onDone()
      }}
      onClose={() => undefined}
    >
      <p className="hint">This server requires the token set in MODBUS_STUDIO_TOKEN.</p>
      <Field label="Token">
        <input type="password" autoFocus value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
    </Modal>
  )
}
