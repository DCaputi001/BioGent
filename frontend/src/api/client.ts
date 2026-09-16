// client.ts
// The only place that talks to the RAG service over HTTP. Owns the request
// shape, the BYO-key header, and turning any failure into a typed ApiError so
// callers never handle a raw Response or an unparsed body.

import { ApiError } from './types'
import type { ApiErrorBody, AskResponse } from './types'

/** Header the API expects the researcher's Anthropic key in (see api.py). */
const API_KEY_HEADER = 'X-Anthropic-Api-Key'

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000'

/** Shown when the failure has no researcher-readable message of its own. */
const UNREACHABLE_MESSAGE =
  'Could not reach the document service. Check that it is running, then try again.'
const UNREADABLE_MESSAGE = 'The document service returned an unexpected response.'

function isApiErrorBody(body: unknown): body is ApiErrorBody {
  if (typeof body !== 'object' || body === null || !('error' in body)) return false
  const error = (body as { error: unknown }).error
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as { message?: unknown }).message === 'string'
  )
}

/**
 * Turn a non-2xx response into an ApiError.
 *
 * The documented error shape is preferred, but anything between the browser
 * and the service -- a proxy, or CloudFront once deployed -- can return HTML
 * or an empty body instead, so an unreadable body still has to produce
 * something a researcher can act on rather than throwing a parse error.
 */
async function toApiError(response: Response): Promise<ApiError> {
  let body: unknown
  try {
    body = await response.json()
  } catch {
    return new ApiError('unreadable_response', UNREADABLE_MESSAGE, true, response.status)
  }

  if (isApiErrorBody(body)) {
    const { code, message, retryable } = body.error
    return new ApiError(code ?? 'unknown_error', message, retryable ?? false, response.status)
  }
  return new ApiError('unreadable_response', UNREADABLE_MESSAGE, true, response.status)
}

/**
 * Ask one question, on the researcher's own Anthropic key.
 *
 * The key goes in a header, never a query string: URLs are written to server
 * access logs and browser history, headers are not. `signal` lets a caller
 * abandon a slow request when a newer question is asked.
 *
 * Throws ApiError for every failure, including a network failure, so callers
 * have exactly one error type to render.
 */
export async function askQuestion(
  question: string,
  apiKey: string,
  signal?: AbortSignal,
): Promise<AskResponse> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}/ask`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        [API_KEY_HEADER]: apiKey,
      },
      body: JSON.stringify({ question }),
      signal,
    })
  } catch (cause) {
    // An aborted request is the caller's own doing, not a failure to report.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError('service_unreachable', UNREACHABLE_MESSAGE, true, 0)
  }

  if (!response.ok) throw await toApiError(response)

  return (await response.json()) as AskResponse
}
