// types.ts
// TypeScript mirror of the RAG service's HTTP contract (services/rag/app/api.py
// and app/errors.py). Kept in one file so a backend shape change breaks the
// build here rather than surfacing as a runtime surprise for a researcher --
// the reason TypeScript was chosen in ARCHITECTURE.md.

/** Successful POST /ask response. */
export interface AskResponse {
  /**
   * The history entry this answer was saved as. Null when saving failed --
   * the answer still arrives, it just is not in the history list.
   */
  id: string | null
  answer: string
  /** Filenames of the documents the answer was grounded in. */
  sources: string[]
}

/** One entry of GET /api/questions: a past question and its answer. */
export interface QuestionRecord {
  id: string
  question: string
  answer: string
  /** Filenames as they were when answered; may name a since-deleted document. */
  sources: string[]
  /** ISO 8601 timestamp. */
  created_at: string
}

/**
 * Where a document has got to. Mirrors app/models.py's DOCUMENT_STATUSES.
 *
 * A union rather than `string`, so a status the backend can never send is a
 * compile error here instead of a branch that silently never runs.
 */
export type DocumentStatus = 'pending' | 'processing' | 'ready' | 'failed'

/** Statuses where the worker has not finished, so the UI keeps polling. */
export const IN_PROGRESS_STATUSES: readonly DocumentStatus[] = ['pending', 'processing']

/** One row of GET /api/documents. */
export interface DocumentResponse {
  id: string
  filename: string
  status: DocumentStatus
  chunk_count: number | null
  /** Set only when status is 'failed'; already written for a researcher. */
  error_message: string | null
}

/**
 * The form fields S3 requires alongside the file in a presigned POST.
 *
 * Opaque on purpose: they are a signed policy plus its signature, and the
 * browser's only correct move is to pass every one of them through unchanged.
 */
export type PresignedPostFields = Record<string, string>

/** Successful POST /api/documents response: permission to upload one file. */
export interface UploadResponse {
  document_id: string
  /** The sanitized name the document is stored under, which may differ from the file's. */
  filename: string
  upload_url: string
  fields: PresignedPostFields
  max_bytes: number
}

/** Error body the API returns for every failure, whatever the status code. */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    retryable: boolean
  }
}

/**
 * A failed request, already carrying a message written for a researcher.
 *
 * The backend composes these messages (see errors.py), so the UI renders
 * `message` directly instead of maintaining its own copy of the wording.
 * `code` is the stable value to branch on; step 7 uses it for per-error
 * treatment, and `retryable` for whether to offer a retry.
 */
export class ApiError extends Error {
  readonly code: string
  readonly retryable: boolean
  readonly status: number

  constructor(code: string, message: string, retryable: boolean, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.retryable = retryable
    this.status = status
  }
}
