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

export function DocumentList({ documents, onRemove }: DocumentListProps) {
  if (documents.length === 0) {
    return (
      <p className="hint">
        No documents yet. Upload a paper above, then ask questions about it.
      </p>
    )
  }

  return (
    <ul className="documents">
      {documents.map((document) => (
        <li key={document.id} className={`document document-${document.status}`}>
          <div className="document-row">
            <span className="document-name">{document.filename}</span>

            {/* aria-live so a screen reader hears a document finish, rather
                than the change happening silently on a poll. */}
            <span className={`badge badge-${document.status}`} aria-live="polite">
              {STATUS_LABELS[document.status]}
            </span>

            <button
              type="button"
              className="link"
              onClick={() => onRemove(document.id)}
              aria-label={`Remove ${document.filename}`}
            >
              Remove
            </button>
          </div>

          {document.status === 'failed' && document.error_message && (
            <p className="error" role="alert">
              {document.error_message}
            </p>
          )}

          {document.status === 'ready' && document.chunk_count !== null && (
            <p className="hint">{document.chunk_count} sections indexed</p>
          )}
        </li>
      ))}
    </ul>
  )
}
