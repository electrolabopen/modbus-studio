import { useEffect, useState } from 'react'
import { ApiError, api } from '../api/client'
import type { MapError, PollView } from '../api/types'
import { useStudio } from '../store'
import { Modal } from './Modal'

function mapErrors(err: unknown): MapError[] | null {
  if (!(err instanceof ApiError) || !err.body || typeof err.body !== 'object') return null
  const errors = (err.body as { errors?: unknown }).errors
  return Array.isArray(errors) ? (errors as MapError[]) : null
}

/** Rows that are neither blank, a comment nor the header. */
const countRows = (text: string) =>
  Math.max(
    0,
    text.split(/\r?\n/).filter((l) => l.trim() && !l.trimStart().startsWith('#')).length - 1,
  )

interface Props {
  view: PollView
  file: File
  onClose: () => void
}

/** Confirm and apply a CSV register map to a window; lists problems by line. */
export function CsvImportDialog({ view, file, onClose }: Props) {
  const def = view.definition
  const upsert = useStudio((s) => s.upsertPoll)
  const [text, setText] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lineErrors, setLineErrors] = useState<MapError[]>([])

  useEffect(() => {
    let cancelled = false
    file
      .text()
      .then((content) => !cancelled && setText(content))
      .catch((err: unknown) => !cancelled && setError(`Cannot read ${file.name}: ${String(err)}`))
    return () => {
      cancelled = true
    }
  }, [file])

  const submit = async () => {
    if (text === null) return
    setBusy(true)
    setError(null)
    setLineErrors([])
    try {
      upsert(await api.importRegisterMap(def.id, text))
      onClose()
    } catch (err) {
      const errors = mapErrors(err)
      if (errors) setLineErrors(errors)
      else setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const last = def.address + def.quantity - 1
  return (
    <Modal
      title="Import register map"
      submitLabel="Apply"
      busy={busy || text === null || lineErrors.length > 0}
      error={error}
      onSubmit={submit}
      onClose={onClose}
      focusCancel
    >
      <p className="hint">
        <strong>{file.name}</strong>
        {text !== null && ` · ${countRows(text)} rows`} → {def.name || def.id} (addresses{' '}
        {def.address}–{last})
      </p>
      <p className="hint">
        Replaces the data types, byte orders, scales, units and aliases of this window.
        Addresses not in the file go back to the window format.
      </p>
      {lineErrors.length > 0 && (
        <>
          <p className="form-error">Nothing was applied. Fix these lines and import again:</p>
          <ul className="error-list mono" aria-label="CSV problems">
            {lineErrors.map((e, i) => (
              <li key={i}>
                line {e.line}: {e.message}
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  )
}
