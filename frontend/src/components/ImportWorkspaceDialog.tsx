import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Workspace } from '../api/types'
import { useStudio } from '../store'
import { Modal } from './Modal'

type Parsed = { ok: true; workspace: Workspace } | { ok: false; error: string }

function parse(text: string): Parsed {
  try {
    const data = JSON.parse(text) as Partial<Workspace>
    if (!data || !Array.isArray(data.connections) || !Array.isArray(data.polls)) {
      return { ok: false, error: 'Not a modbus-studio workspace (no connections/polls lists).' }
    }
    return { ok: true, workspace: data as Workspace }
  } catch (err) {
    return { ok: false, error: `Not valid JSON: ${String(err)}` }
  }
}

/** Load a workspace file: replace the current session or merge into it. */
export function ImportWorkspaceDialog({ file, onClose }: { file: File; onClose: () => void }) {
  // Two primitive selectors: an object built in the selector would re-render forever.
  const current = {
    connections: useStudio((s) => Object.keys(s.connections).length),
    polls: useStudio((s) => Object.keys(s.polls).length),
  }
  const [parsed, setParsed] = useState<Parsed | null>(null)
  const [mode, setMode] = useState<'replace' | 'merge'>('replace')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    file
      .text()
      .then((text) => !cancelled && setParsed(parse(text)))
      .catch((err: unknown) => !cancelled && setParsed({ ok: false, error: String(err) }))
    return () => {
      cancelled = true
    }
  }, [file])

  const submit = async () => {
    if (!parsed?.ok) return
    setBusy(true)
    setError(null)
    try {
      // The server pushes a snapshot over the WebSocket after the import.
      await api.importWorkspace(parsed.workspace, mode)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const ws = parsed?.ok ? parsed.workspace : null
  return (
    <Modal
      title="Import workspace"
      submitLabel="Import"
      busy={busy || !ws}
      error={error ?? (parsed && !parsed.ok ? parsed.error : null)}
      onSubmit={submit}
      onClose={onClose}
      focusCancel
    >
      <p className="hint">
        <strong>{file.name}</strong>
        {ws &&
          ` · ${ws.connections.length} connection${ws.connections.length === 1 ? '' : 's'}, ` +
            `${ws.polls.length} window${ws.polls.length === 1 ? '' : 's'}`}
      </p>
      {ws && (
        <ul className="hint" aria-label="Workspace contents">
          {ws.connections.map((c) => (
            <li key={c.id}>
              {c.name || c.id}
              {c.read_only && ' (read-only)'} ·{' '}
              {ws.polls.filter((p) => p.connection_id === c.id).length} window(s)
            </li>
          ))}
        </ul>
      )}
      <label className="choice">
        <input
          type="radio"
          name="import-mode"
          checked={mode === 'replace'}
          onChange={() => setMode('replace')}
        />
        <span>
          Replace the current session
          <small>
            Closes the {current.connections} connection(s) and {current.polls} window(s) open now.
          </small>
        </span>
      </label>
      <label className="choice">
        <input
          type="radio"
          name="import-mode"
          checked={mode === 'merge'}
          onChange={() => setMode('merge')}
        />
        <span>
          Add to the current session
          <small>Fails if a connection or window id is already in use.</small>
        </span>
      </label>
    </Modal>
  )
}
