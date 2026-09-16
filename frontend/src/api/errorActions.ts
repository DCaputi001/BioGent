// errorActions.ts
// Decides what a researcher can DO about a failure, given the error code the
// backend returned (services/rag/app/errors.py).
//
// Grouped by remedy rather than by status code, because that is what the UI
// renders: a rejected key needs a different key, an empty balance needs
// credit, and a rate limit just needs another try. Offering "try again" on an
// error that retrying cannot fix is worse than offering nothing.
//
// The message itself always comes from the backend; nothing here restates it.

import type { ApiError } from './types'

export type ErrorRemedy = 'fix-key' | 'add-credit' | 'retry' | 'none'

/** Codes where the key itself is the problem, so retrying is pointless. */
const KEY_PROBLEM_CODES = new Set(['invalid_api_key', 'missing_api_key', 'permission_denied'])

export function remedyFor(error: ApiError): ErrorRemedy {
  if (KEY_PROBLEM_CODES.has(error.code)) return 'fix-key'
  if (error.code === 'insufficient_credit') return 'add-credit'
  // retryable covers rate limits, upstream trouble, and an unreachable
  // service; unknown codes from a newer backend fall through to it too.
  if (error.retryable) return 'retry'
  return 'none'
}

/**
 * An extra line of context the backend cannot know to write.
 *
 * Only for cases where the cause is almost certainly local: a service that
 * cannot be reached in development nearly always means the API is not
 * running, and naming the command saves a confusing debugging session.
 */
export function localHintFor(error: ApiError): string | null {
  if (error.code === 'service_unreachable') {
    return 'If you are running this locally, start the API with: uv run uvicorn app.api:app --reload --port 8000'
  }
  return null
}
