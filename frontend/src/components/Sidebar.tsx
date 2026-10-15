import { useState } from 'react'
import { ApiError, api } from '../api/client'
import type { ConnectionView } from '../api/types'
import { useStudio } from '../store'

export function Sidebar() {
  const connections = useStudio((s) => s.connections)
  const [error, setError] = useState<string | null>(null)

  const remove = async (id: string) => {
    setError(null)
    try {
      await api.deleteConnection(id)
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        if (window.confirm(`${err.message}\n\nDelete the connection and its windows?`)) {
          await api.deleteConnection(id, true).catch((e: unknown) => setError(String(e)))
        }
      } else {
        setError(err instanceof Error ? err.message : String(err))
      }
    }
  }

  const toggleReadOnly = async (view: ConnectionView) => {
    setError(null)
    const config = { ...view.config, read_only: !view.config.read_only }
    try {
      useStudio.getState().upsertConnection(await api.updateConnection(config.id, config))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const list = Object.values(connections)
  return (
    <aside className="sidebar">
      <h2>Connections</h2>
      {list.length === 0 && <p className="muted small">No connections yet.</p>}
      <ul>
        {list.map((view) => {
          const { config, state, stats, last_error } = view
          const label = config.name || config.id
          return (
            <li key={config.id} className="conn">
              <span className={`dot dot-${state}`} title={state} />
              <div className="conn-text">
                <div className="conn-head">
                  <div className="conn-name">{label}</div>
                  <button
                    className={`btn btn-small${config.read_only ? ' btn-locked' : ''}`}
                    aria-pressed={!!config.read_only}
                    aria-label={`Read-only ${label}`}
                    title={
                      config.read_only
                        ? 'Read-only: writes are blocked. Click to allow writes.'
                        : 'Writes allowed. Click to make this connection read-only.'
                    }
                    onClick={() => toggleReadOnly(view)}
                  >
                    {config.read_only ? 'RO' : 'RW'}
                  </button>
                  <button
                    className="btn btn-small"
                    aria-label={`Delete connection ${label}`}
                    onClick={() => remove(config.id)}
                  >
                    ✕
                  </button>
                </div>
                <div className="muted small mono">
                  {config.type === 'rtu' ? (
                    <>
                      {config.serial_port} ·{' '}
                      <span className="nowrap">
                        {config.baudrate} {config.bytesize}
                        {config.parity}
                        {config.stopbits}
                      </span>
                    </>
                  ) : (
                    `${config.host}:${config.port}`
                  )}
                  {config.type === 'rtu_over_tcp' && ' · RTU/TCP'}
                </div>
                <div className="muted small">
                  {stats.responses} ok · {stats.timeouts} timeouts · {stats.exceptions} exc
                </div>
                {last_error && state !== 'connected' && (
                  <div className="conn-error small">{last_error}</div>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      {error && <p className="form-error">{error}</p>}
    </aside>
  )
}
