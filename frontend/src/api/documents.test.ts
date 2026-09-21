// documents.test.ts
// The document half of the HTTP client, against a stubbed fetch.
//
// Kept separate from client.test.ts, which covers askQuestion, because the
// upload path talks to two different servers with different rules: our API
// speaks the documented JSON error shape, S3 speaks XML and must never see
// the Cognito token.

import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  completeUpload,
  deleteDocument,
  listDocuments,
  requestUpload,
  uploadToS3,
} from './client'
import { ApiError } from './types'

const ACCESS_TOKEN = 'header.payload.signature'
const DOCUMENT_ID = '11111111-2222-3333-4444-555555555555'

function mockFetch(response: Response) {
  const fetchMock = vi.fn((_url: string, _init: RequestInit) => Promise.resolve(response))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function mockFetchRejection(reason: unknown) {
  const fetchMock = vi.fn((_url: string, _init: RequestInit) => Promise.reject(reason))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

const PRESIGNED = {
  document_id: DOCUMENT_ID,
  filename: 'paper.pdf',
  upload_url: 'https://bucket.s3.amazonaws.com/',
  fields: { key: 'users/abc/documents/paper.pdf', policy: 'signed-policy' },
  max_bytes: 52428800,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('requestUpload', () => {
  it('sends the filename and carries the session', async () => {
    const fetchMock = mockFetch(jsonResponse(PRESIGNED))

    const result = await requestUpload('paper.pdf', ACCESS_TOKEN)

    const [url, init] = fetchMock.mock.calls[0]
    const headers = init.headers as Record<string, string>
    expect(url.endsWith('/documents')).toBe(true)
    expect(headers['Authorization']).toBe(`Bearer ${ACCESS_TOKEN}`)
    expect(JSON.parse(init.body as string)).toEqual({ filename: 'paper.pdf' })
    expect(result.upload_url).toBe(PRESIGNED.upload_url)
  })

  it('surfaces an unsupported file type as the backend described it', async () => {
    mockFetch(
      jsonResponse(
        {
          error: {
            code: 'unsupported_file_type',
            message: '.exe cannot be read. Upload one of: .pdf, .txt, .md.',
            retryable: false,
          },
        },
        415,
      ),
    )

    const error = await requestUpload('virus.exe', ACCESS_TOKEN).catch((caught) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('unsupported_file_type')
  })
})

describe('uploadToS3', () => {
  function file(): File {
    return new File(['pretend pdf bytes'], 'paper.pdf', { type: 'application/pdf' })
  }

  it('posts every presigned field, with the file last', async () => {
    // S3 ignores any part after the file, so a field appended after it is
    // silently dropped and the upload then fails its own policy check.
    const fetchMock = mockFetch(new Response(null, { status: 204 }))

    await uploadToS3(PRESIGNED.upload_url, PRESIGNED.fields, file())

    const [url, init] = fetchMock.mock.calls[0]
    const form = init.body as FormData
    const names = [...form.keys()]

    expect(url).toBe(PRESIGNED.upload_url)
    expect(names).toEqual(['key', 'policy', 'file'])
    expect(form.get('policy')).toBe('signed-policy')
  })

  it('never sends the Cognito token to S3', async () => {
    // The presigned fields are the only credential involved. A bearer token
    // here would be useless to S3 and a leak of the researcher's session to a
    // party that has no business holding it.
    const fetchMock = mockFetch(new Response(null, { status: 204 }))

    await uploadToS3(PRESIGNED.upload_url, PRESIGNED.fields, file())

    const headers = (fetchMock.mock.calls[0][1].headers ?? {}) as Record<string, string>
    expect(headers['Authorization']).toBeUndefined()
  })

  it('sets no Content-Type, so the browser can add the multipart boundary', async () => {
    const fetchMock = mockFetch(new Response(null, { status: 204 }))

    await uploadToS3(PRESIGNED.upload_url, PRESIGNED.fields, file())

    const headers = (fetchMock.mock.calls[0][1].headers ?? {}) as Record<string, string>
    expect(headers['Content-Type']).toBeUndefined()
  })

  it('treats a 204 with no body as success', async () => {
    mockFetch(new Response(null, { status: 204 }))

    await expect(uploadToS3(PRESIGNED.upload_url, PRESIGNED.fields, file())).resolves
      .toBeUndefined()
  })

  it("explains S3's size rejection in terms a researcher can act on", async () => {
    // The one rejection the size policy actually produces, and it arrives as
    // XML rather than the documented JSON error shape.
    mockFetch(
      new Response('<Error><Code>EntityTooLarge</Code></Error>', { status: 400 }),
    )

    const error = await uploadToS3(PRESIGNED.upload_url, PRESIGNED.fields, file()).catch(
      (caught) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('file_too_large')
    expect(error.retryable).toBe(false)
  })

  it('reports any other S3 failure as retryable rather than as a parse error', async () => {
    mockFetch(new Response('<Error><Code>InternalError</Code></Error>', { status: 500 }))

    const error = await uploadToS3(PRESIGNED.upload_url, PRESIGNED.fields, file()).catch(
      (caught) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect(error.retryable).toBe(true)
  })

  it('reports an unreachable bucket rather than throwing a raw network error', async () => {
    mockFetchRejection(new TypeError('Failed to fetch'))

    const error = await uploadToS3(PRESIGNED.upload_url, PRESIGNED.fields, file()).catch(
      (caught) => caught,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('upload_unreachable')
  })
})

describe('completeUpload', () => {
  it('posts to the document it was given and returns the updated row', async () => {
    const fetchMock = mockFetch(
      jsonResponse({
        id: DOCUMENT_ID,
        filename: 'paper.pdf',
        status: 'processing',
        chunk_count: null,
        error_message: null,
      }),
    )

    const result = await completeUpload(DOCUMENT_ID, ACCESS_TOKEN)

    expect(fetchMock.mock.calls[0][0].endsWith(`/documents/${DOCUMENT_ID}/complete`)).toBe(true)
    expect(result.status).toBe('processing')
  })
})

describe('listDocuments', () => {
  it('returns the researcher’s documents', async () => {
    mockFetch(
      jsonResponse([
        {
          id: DOCUMENT_ID,
          filename: 'paper.pdf',
          status: 'ready',
          chunk_count: 12,
          error_message: null,
        },
      ]),
    )

    const documents = await listDocuments(ACCESS_TOKEN)

    expect(documents).toHaveLength(1)
    expect(documents[0].chunk_count).toBe(12)
  })

  it('surfaces an expired session as invalid_token rather than an empty list', async () => {
    // An empty list would read as "you have no documents", which is a very
    // different thing to tell someone than "sign in again".
    mockFetch(
      jsonResponse(
        { error: { code: 'invalid_token', message: 'Your session has expired.', retryable: false } },
        401,
      ),
    )

    const error = await listDocuments(ACCESS_TOKEN).catch((caught) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('invalid_token')
  })
})

describe('deleteDocument', () => {
  it('sends a DELETE and expects no body back', async () => {
    const fetchMock = mockFetch(new Response(null, { status: 204 }))

    await expect(deleteDocument(DOCUMENT_ID, ACCESS_TOKEN)).resolves.toBeUndefined()

    const [url, init] = fetchMock.mock.calls[0]
    expect(init.method).toBe('DELETE')
    expect(url.endsWith(`/documents/${DOCUMENT_ID}`)).toBe(true)
  })

  it('surfaces another researcher’s document as not found', async () => {
    mockFetch(
      jsonResponse(
        {
          error: {
            code: 'document_not_found',
            message: 'That document is not in your library.',
            retryable: false,
          },
        },
        404,
      ),
    )

    const error = await deleteDocument(DOCUMENT_ID, ACCESS_TOKEN).catch((caught) => caught)

    expect(error.code).toBe('document_not_found')
  })
})
