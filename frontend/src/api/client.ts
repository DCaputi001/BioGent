// client.ts
// The only place that talks to the RAG service over HTTP. Owns the request
// shape, the BYO-key header, and turning any failure into a typed ApiError so
// callers never handle a raw Response or an unparsed body.

import { ApiError } from './types'
import type {
  ApiErrorBody,
  AskResponse,
  DocumentResponse,
  PresignedPostFields,
  UploadResponse,
} from './types'

/** Header the API expects the researcher's Anthropic key in (see api.py). */
const API_KEY_HEADER = 'X-Anthropic-Api-Key'

// Includes the /api prefix the service serves under. In production this is the
// relative "/api": CloudFront serves the app and the API from one domain, so
// the request is same-origin and CORS never comes into play.
const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api'

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
 * Call the API and return the response, or throw a typed ApiError.
 *
 * Every exported function below goes through here, so "a network failure and
 * a 500 are both an ApiError" is stated once rather than repeated per call.
 */
async function request(path: string, init: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, init)
  } catch (cause) {
    // An aborted request is the caller's own doing, not a failure to report.
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause
    throw new ApiError('service_unreachable', UNREACHABLE_MESSAGE, true, 0)
  }

  if (!response.ok) throw await toApiError(response)
  return response
}

/** The Cognito session, which decides whose documents a request can reach. */
function authHeaders(accessToken: string): Record<string, string> {
  return { Authorization: `Bearer ${accessToken}` }
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
  accessToken: string,
  signal?: AbortSignal,
): Promise<AskResponse> {
  const response = await request('/ask', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      // Two credentials answering two questions: the bearer token says whose
      // documents to search, the key says whose Anthropic account pays.
      ...authHeaders(accessToken),
      [API_KEY_HEADER]: apiKey,
    },
    body: JSON.stringify({ question }),
    signal,
  })

  return (await response.json()) as AskResponse
}

/**
 * Step 1 of an upload: reserve a document and get permission to send the file.
 *
 * Returns a presigned POST, not an upload of its own -- the bytes go
 * browser-to-S3 and never through the service. That is partly cost, but mostly
 * necessity: CloudFront caps a request body at 1MB, well under a real paper.
 */
export async function requestUpload(
  filename: string,
  accessToken: string,
): Promise<UploadResponse> {
  const response = await request('/documents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(accessToken) },
    body: JSON.stringify({ filename }),
  })

  return (await response.json()) as UploadResponse
}

/**
 * Step 2: send the file itself, straight to S3.
 *
 * Deliberately NOT routed through request() above. This talks to S3, not to
 * our API: it must not carry the Cognito token (the presigned fields are the
 * only credential involved, and sending a bearer token to a third party is
 * both useless and a leak), and S3 answers with XML rather than our error
 * shape, so the JSON parsing in toApiError would find nothing to read.
 */
export async function uploadToS3(
  uploadUrl: string,
  fields: PresignedPostFields,
  file: File,
): Promise<void> {
  const form = new FormData()
  for (const [name, value] of Object.entries(fields)) {
    form.append(name, value)
  }
  // The file must be appended LAST. S3 ignores anything after the file part,
  // so a field added below this line is silently dropped and the upload then
  // fails its own policy check.
  form.append('file', file)

  let response: Response
  try {
    // No Content-Type header set by hand: the browser has to add the multipart
    // boundary, and setting it here would omit that and break the parse.
    response = await fetch(uploadUrl, { method: 'POST', body: form })
  } catch {
    throw new ApiError('upload_unreachable', 'Could not reach file storage. Try again.', true, 0)
  }

  if (response.ok) return

  // S3 enforces the size limit through the presigned policy, so this is the
  // one rejection a researcher can actually act on -- and it arrives from S3
  // in XML, not from our API in the documented shape.
  const body = await response.text().catch(() => '')
  if (body.includes('EntityTooLarge')) {
    throw new ApiError(
      'file_too_large',
      'That file is larger than the upload limit. Try a smaller file.',
      false,
      response.status,
    )
  }

  throw new ApiError(
    'upload_failed',
    'The file could not be uploaded. Try again.',
    true,
    response.status,
  )
}

/**
 * Step 3: tell the API the bytes have landed, so it can queue the work.
 *
 * Separate from the upload because S3 cannot call back into the service. If
 * this never runs -- the tab closes mid-upload -- the document stays visible
 * as 'pending' rather than vanishing, and re-uploading reuses the same row.
 */
export async function completeUpload(
  documentId: string,
  accessToken: string,
): Promise<DocumentResponse> {
  const response = await request(`/documents/${documentId}/complete`, {
    method: 'POST',
    headers: authHeaders(accessToken),
  })

  return (await response.json()) as DocumentResponse
}

/** The researcher's own documents and where each has got to. Polled while any is in progress. */
export async function listDocuments(accessToken: string): Promise<DocumentResponse[]> {
  const response = await request('/documents', {
    method: 'GET',
    headers: authHeaders(accessToken),
  })

  return (await response.json()) as DocumentResponse[]
}

/** Remove a document: its chunks, its row, and its bytes. Answers 204, with no body to read. */
export async function deleteDocument(documentId: string, accessToken: string): Promise<void> {
  await request(`/documents/${documentId}`, {
    method: 'DELETE',
    headers: authHeaders(accessToken),
  })
}
