// types.ts
// TypeScript mirror of the RAG service's HTTP contract (services/rag/app/api.py
// and app/errors.py). Kept in one file so a backend shape change breaks the
// build here rather than surfacing as a runtime surprise for a researcher --
// the reason TypeScript was chosen in ARCHITECTURE.md.

/** Successful POST /ask response. */
export interface AskResponse {
  answer: string
  /** Filenames of the documents the answer was grounded in. */
  sources: string[]
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
