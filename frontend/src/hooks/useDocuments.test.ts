// useDocuments.test.ts
// The upload sequence and the polling lifecycle, with the HTTP client mocked.
//
// Polling is the part worth pinning hardest. Too eager and every open tab
// generates requests forever; stopped too early and a document sits at
// "Reading it" until the researcher reloads the page, with nothing saying it
// actually finished.

import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  completeUpload,
  deleteDocument,
  listDocuments,
  requestUpload,
  uploadToS3,
} from '../api/client'
import { ApiError } from '../api/types'
import type { DocumentResponse } from '../api/types'
import { POLL_INTERVAL_MS, useDocuments } from './useDocuments'

vi.mock('../api/client', () => ({
  requestUpload: vi.fn(),
  uploadToS3: vi.fn(),
  completeUpload: vi.fn(),
  listDocuments: vi.fn(),
  deleteDocument: vi.fn(),
}))

const requestUploadMock = vi.mocked(requestUpload)
const uploadToS3Mock = vi.mocked(uploadToS3)
const completeUploadMock = vi.mocked(completeUpload)
const listDocumentsMock = vi.mocked(listDocuments)
const deleteDocumentMock = vi.mocked(deleteDocument)

const TOKEN = 'header.payload.signature'
const DOCUMENT_ID = '11111111-2222-3333-4444-555555555555'

function document(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: DOCUMENT_ID,
    filename: 'paper.pdf',
    status: 'ready',
    chunk_count: 12,
    error_message: null,
    ...overrides,
  }
}

const PRESIGNED = {
  document_id: DOCUMENT_ID,
  filename: 'paper.pdf',
  upload_url: 'https://bucket.s3.amazonaws.com/',
  fields: { key: 'users/abc/documents/paper.pdf' },
  max_bytes: 52428800,
}

function pdf(): File {
  return new File(['bytes'], 'paper.pdf', { type: 'application/pdf' })
}

beforeEach(() => {
  vi.clearAllMocks()
  listDocumentsMock.mockResolvedValue([])
  requestUploadMock.mockResolvedValue(PRESIGNED)
  uploadToS3Mock.mockResolvedValue(undefined)
  completeUploadMock.mockResolvedValue(document({ status: 'processing' }))
  deleteDocumentMock.mockResolvedValue(undefined)
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useDocuments', () => {
  it('reads the library once on mount', async () => {
    listDocumentsMock.mockResolvedValue([document()])

    const { result } = renderHook(() => useDocuments(TOKEN))

    await waitFor(() => expect(result.current.documents).toHaveLength(1))
    expect(listDocumentsMock).toHaveBeenCalledWith(TOKEN)
  })

  it('does nothing at all without a session', async () => {
    renderHook(() => useDocuments(undefined))

    expect(listDocumentsMock).not.toHaveBeenCalled()
  })

  it('uploads in order: reserve, send the bytes, then queue it', async () => {
    // Order matters and is not incidental: the presigned fields come from the
    // first call, and queueing before the bytes exist gives the worker a
    // document it cannot download.
    const calls: string[] = []
    requestUploadMock.mockImplementation(async () => {
      calls.push('request')
      return PRESIGNED
    })
    uploadToS3Mock.mockImplementation(async () => {
      calls.push('s3')
    })
    completeUploadMock.mockImplementation(async () => {
      calls.push('complete')
      return document({ status: 'processing' })
    })

    const { result } = renderHook(() => useDocuments(TOKEN))
    await act(async () => {
      await result.current.upload(pdf())
    })

    expect(calls).toEqual(['request', 's3', 'complete'])
  })

  it('passes the presigned fields straight through to S3', async () => {
    const { result } = renderHook(() => useDocuments(TOKEN))

    await act(async () => {
      await result.current.upload(pdf())
    })

    expect(uploadToS3Mock).toHaveBeenCalledWith(
      PRESIGNED.upload_url,
      PRESIGNED.fields,
      expect.any(File),
    )
  })

  it('stops the upload when S3 rejects it, and never queues the document', async () => {
    // Queueing after a failed upload would leave the worker looking for bytes
    // that were never stored.
    uploadToS3Mock.mockRejectedValue(
      new ApiError('file_too_large', 'That file is larger than the upload limit.', false, 400),
    )

    const { result } = renderHook(() => useDocuments(TOKEN))
    await act(async () => {
      await result.current.upload(pdf())
    })

    expect(completeUploadMock).not.toHaveBeenCalled()
    expect(result.current.error?.code).toBe('file_too_large')
  })

  it('reports uploading only while the file is in flight', async () => {
    const { result } = renderHook(() => useDocuments(TOKEN))
    expect(result.current.uploading).toBe(false)

    await act(async () => {
      await result.current.upload(pdf())
    })

    // False again afterwards even though the worker is still processing --
    // that progress belongs to the document's own status, not to this flag.
    expect(result.current.uploading).toBe(false)
  })

  it('re-reads the list after an upload rather than appending the new row', async () => {
    // A re-upload reuses the existing document, so appending would show the
    // same filename twice.
    const { result } = renderHook(() => useDocuments(TOKEN))
    listDocumentsMock.mockClear()

    await act(async () => {
      await result.current.upload(pdf())
    })

    expect(listDocumentsMock).toHaveBeenCalled()
  })

  it('removes a document from the list as soon as the delete succeeds', async () => {
    listDocumentsMock.mockResolvedValue([document()])
    const { result } = renderHook(() => useDocuments(TOKEN))
    await waitFor(() => expect(result.current.documents).toHaveLength(1))

    listDocumentsMock.mockResolvedValue([])
    await act(async () => {
      await result.current.remove(DOCUMENT_ID)
    })

    expect(deleteDocumentMock).toHaveBeenCalledWith(DOCUMENT_ID, TOKEN)
    expect(result.current.documents).toHaveLength(0)
  })

  // --- polling ---------------------------------------------------------------

  it('keeps polling while a document is still processing', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    listDocumentsMock.mockResolvedValue([document({ status: 'processing' })])

    const { result } = renderHook(() => useDocuments(TOKEN))
    await waitFor(() => expect(result.current.documents).toHaveLength(1))
    listDocumentsMock.mockClear()

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 2)
    })

    expect(listDocumentsMock).toHaveBeenCalled()
  })

  it('stops polling once nothing is in progress', async () => {
    // The whole reason the interval is conditional: an idle library must not
    // keep every open tab generating requests indefinitely.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    listDocumentsMock.mockResolvedValue([document({ status: 'ready' })])

    const { result } = renderHook(() => useDocuments(TOKEN))
    await waitFor(() => expect(result.current.documents).toHaveLength(1))
    listDocumentsMock.mockClear()

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 3)
    })

    expect(listDocumentsMock).not.toHaveBeenCalled()
  })

  it('does not poll for a document that failed', async () => {
    // Failed is terminal. Polling it forever would never produce a change.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    listDocumentsMock.mockResolvedValue([
      document({ status: 'failed', error_message: 'No readable text.' }),
    ])

    const { result } = renderHook(() => useDocuments(TOKEN))
    await waitFor(() => expect(result.current.documents).toHaveLength(1))
    listDocumentsMock.mockClear()

    await act(async () => {
      vi.advanceTimersByTime(POLL_INTERVAL_MS * 3)
    })

    expect(listDocumentsMock).not.toHaveBeenCalled()
  })

  it('surfaces a failed refresh rather than silently showing a stale list', async () => {
    listDocumentsMock.mockRejectedValue(
      new ApiError('document_store_unavailable', 'The library is unavailable.', true, 503),
    )

    const { result } = renderHook(() => useDocuments(TOKEN))

    await waitFor(() => expect(result.current.error?.code).toBe('document_store_unavailable'))
  })
})
