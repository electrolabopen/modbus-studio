import { useEffect, useRef, useState } from 'react'
import { api, getHealth, getToken, setToken, type Health } from './api/client'
import { connectSocket } from './api/socket'
import { ChartPanel } from './components/ChartPanel'
import { ConnectionDialog } from './components/ConnectionDialog'
import { ExportersDialog, StatusDot } from './components/ExportersDialog'
import { ImportWorkspaceDialog } from './components/ImportWorkspaceDialog'
import { Field, Modal } from './components/Modal'
import { PollDialog } from './components/PollDialog'
import { PollWindow } from './components/PollWindow'
import { Sidebar } from './components/Sidebar'
import { TrafficPanel } from './components/TrafficPanel'
import { WriteLogPanel } from './components/WriteLogPanel'
import { exportersSummary, useExporters } from './exporters'
import { useStudio, type LinkState } from './store'
import { downloadText, fileTimestamp } from './util'
import './App.css'

type BackendState =
  | { kind: 'loading' }
  | { kind: 'online'; health: Health }
  | { kind: 'offline'; error: string }

export default function App() {
  const [backend, setBackend] = useState<BackendState>({ kind: 'loading' })
  const [tokenNeeded, setTokenNeeded] = useState(false)
  const [linkKey, setLinkKey] = useState(0)
  const [panel, setPanel] = useState<Panel | null>(null)

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
        <Toolbar
          enabled={online && link === 'open'}
          panel={panel}
          onTogglePanel={(p) => setPanel((open) => (open === p ? null : p))}
        />
        <div className="topbar-right">
          <LinkBadge backend={backend} link={link} />
        </div>
      </header>
      <div className="main">
        <Sidebar />
        <div className="content">
          <Workspace />
          {panel === 'chart' && <ChartPanel onClose={() => setPanel(null)} />}
          {panel === 'traffic' && <TrafficPanel onClose={() => setPanel(null)} />}
          {panel === 'writes' && <WriteLogPanel onClose={() => setPanel(null)} />}
        </div>
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

type Panel = 'chart' | 'traffic' | 'writes'

interface ToolbarProps {
  enabled: boolean
  panel: Panel | null
  onTogglePanel: (panel: Panel) => void
}

function Toolbar({ enabled, panel, onTogglePanel }: ToolbarProps) {
  const hasConnections = useStudio((s) => Object.keys(s.connections).length > 0)
  const [dialog, setDialog] = useState<'connection' | 'poll' | 'exporters' | null>(null)
  const exporters = useExporters(enabled && dialog !== 'exporters')
  const [importFile, setImportFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  // On narrow screens the buttons live in a drop-down menu.
  const [menuOpen, setMenuOpen] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const toolbar = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (e: Event) => {
      const outside = !toolbar.current?.contains(e.target as Node)
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : outside) setMenuOpen(false)
    }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', close)
    return () => {
      document.removeEventListener('pointerdown', close)
      document.removeEventListener('keydown', close)
    }
  }, [menuOpen])

  const exportWorkspace = async () => {
    setError(null)
    try {
      const workspace = await api.exportWorkspace()
      downloadText(
        `modbus-studio-workspace-${fileTimestamp()}.json`,
        JSON.stringify(workspace, null, 2) + '\n',
        'application/json',
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="toolbar" ref={toolbar}>
      <button
        type="button"
        className="btn menu-toggle"
        aria-expanded={menuOpen}
        aria-controls="toolbar-items"
        onClick={() => setMenuOpen((open) => !open)}
      >
        ☰ Menu
      </button>
      <div
        id="toolbar-items"
        className={menuOpen ? 'toolbar-items open' : 'toolbar-items'}
        // Picking an item closes the menu (the file picker opens all the same).
        onClick={(e) => (e.target as HTMLElement).closest('button') && setMenuOpen(false)}
      >
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
        <button
          className="btn"
          disabled={!enabled}
          title="Download the connections and windows as JSON"
          onClick={exportWorkspace}
        >
          Export workspace
        </button>
        <button
          className="btn"
          disabled={!enabled}
          title="Load connections and windows from a workspace JSON file"
          onClick={() => fileInput.current?.click()}
        >
          Import workspace…
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".json,application/json"
          hidden
          aria-label="Workspace file"
          onChange={(e) => {
            setImportFile(e.target.files?.[0] ?? null)
            e.target.value = ''
          }}
        />
        <button
          className="btn"
          aria-pressed={panel === 'chart'}
          disabled={!enabled}
          onClick={() => onTogglePanel('chart')}
        >
          Chart
        </button>
        <button
          className="btn"
          aria-pressed={panel === 'traffic'}
          disabled={!enabled}
          onClick={() => onTogglePanel('traffic')}
        >
          Traffic
        </button>
        <button
          className="btn"
          aria-pressed={panel === 'writes'}
          disabled={!enabled}
          onClick={() => onTogglePanel('writes')}
        >
          Write log
        </button>
        <button
          className="btn btn-exporters"
          disabled={!enabled}
          title={exportersSummary(exporters)}
          onClick={() => setDialog('exporters')}
        >
          {exporters &&
            (['influxdb', 'mqtt'] as const)
              .filter((kind) => exporters[kind].status.state !== 'disabled')
              .map((kind) => <StatusDot key={kind} status={exporters[kind].status} />)}
          Exporters
        </button>
      </div>
      {error && (
        <span className="toolbar-error" role="alert">
          {error}
        </span>
      )}
      {importFile && (
        <ImportWorkspaceDialog file={importFile} onClose={() => setImportFile(null)} />
      )}
      {dialog === 'connection' && <ConnectionDialog onClose={() => setDialog(null)} />}
      {dialog === 'poll' && <PollDialog onClose={() => setDialog(null)} />}
      {dialog === 'exporters' && <ExportersDialog onClose={() => setDialog(null)} />}
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
