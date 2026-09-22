// DocumentList.tsx
// The researcher's library: one row per document, its progress, and a way to
// remove it.
//
// A failed row shows the backend's own error_message unchanged. The worker
// already writes those for a researcher rather than for a log (see
// worker.py), so re-interpreting them here would only add a second, worse
// version of the same sentence -- the same reason ErrorBanner renders
// ApiError.message directly.

import type { DocumentResponse, DocumentStatus } from '../api/types'
import { SpectrumRing } from './SpectrumRing'

/** What each status means to someone waiting on it, rather than its raw name. */
const STATUS_LABELS: Record<DocumentStatus, string> = {
  pending: 'Waiting',
  processing: 'Reading it',
  ready: 'Ready',
  failed: 'Could not read',
}

interface DocumentListProps {
  documents: DocumentResponse[]
  onRemove: (documentId: string) => void
}

/**
 * The mark beside a status. The ring turns while the worker is reading, the
 * same way it does while an answer is being written; a finished or failed
 * document gets a still dot in one of the ring's own colours.
 */
function StatusMark({ status }: { status: DocumentStatus }) {
  if (status === 'processing') return <SpectrumRing size="0.8rem" spinning />
  return <span className={`status-dot status-dot-${status}`} aria-hidden="true" />
}

export function DocumentList({ documents, onRemove }: DocumentListProps) {
  if (documents.length === 0) {
    return (
      <p className="hint rail-empty">
        No documents yet. Upload a paper above, then ask questions about it.
      </p>
    )
  }

  return (
    <ul className="documents">
      {documents.map((document) => (
        <li key={document.id} className={`document document-${document.status}`}>
          <div className="document-row">
            {/* Truncated on screen, so the full name is kept for hover. */}
            <span className="document-name" title={document.filename}>
              {document.filename}
            </span>
            <button
              type="button"
              className="button-remove"
              onClick={() => onRemove(document.id)}
              aria-label={`Remove ${document.filename}`}
            >
              Remove
            </button>
          </div>

          <div className="document-meta">
            <StatusMark status={document.status} />
            {/* aria-live so a screen reader hears a document finish, rather
                than the change happening silently on a poll. */}
            <span className="document-status" aria-live="polite">
              {STATUS_LABELS[document.status]}
            </span>
            {document.status === 'ready' && document.chunk_count !== null && (
              <span className="document-count">{document.chunk_count} sections indexed</span>
            )}
          </div>

          {document.status === 'failed' && document.error_message && (
            <p className="field-error" role="alert">
              {document.error_message}
            </p>
          )}
        </li>
      ))}
    </ul>
  )
}
