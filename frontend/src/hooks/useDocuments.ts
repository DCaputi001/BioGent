// useDocuments.ts
// Owns the researcher's document library: the list, the three-step upload, and
// the polling that reflects a worker's progress back into the UI.
//
// Split out of App.tsx the same way useApiKey is, so App composes views rather
// than knowing the shape of every HTTP call. Takes the access token as an
// argument instead of reading it from the auth context, which keeps it a plain
// data hook that a test can drive without an OIDC provider.

import { useCallback, useEffect, useState } from 'react'
import {
  completeUpload,
  deleteDocument,
  listDocuments,
  requestUpload,
  uploadToS3,
} from '../api/client'
import { ApiError, IN_PROGRESS_STATUSES } from '../api/types'
import type { DocumentResponse } from '../api/types'

/**
 * How often to re-read the list while something is processing.
 *
 * Docling plus embedding runs for minutes, so this is about a progress bar
 * moving, not about latency. Faster would multiply requests across every open
 * tab for no visible gain.
 */
export const POLL_INTERVAL_MS = 4000

const UNEXPECTED_ERROR = new ApiError(
  'unexpected_error',
  'Something went wrong handling that document.',
  true,
  0,
)

function asApiError(caught: unknown): ApiError {
  return caught instanceof ApiError ? caught : UNEXPECTED_ERROR
}

export interface DocumentsState {
  documents: DocumentResponse[]
  /** True while a file is being uploaded, not while the worker is processing it. */
  uploading: boolean
  error: ApiError | null
  upload: (file: File) => Promise<void>
  remove: (documentId: string) => Promise<void>
  refresh: () => Promise<void>
  clearError: () => void
}

export function useDocuments(accessToken: string | undefined): DocumentsState {
  const [documents, setDocuments] = useState<DocumentResponse[]>([])
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  // The token is a plain dependency rather than something held in a ref. It
  // changes only when the OIDC library refreshes it, roughly hourly, so the
  // polling interval restarting then costs nothing -- and a ref written during
  // render is the pattern React warns about.
  const refresh = useCallback(async () => {
    if (!accessToken) return

    try {
      setDocuments(await listDocuments(accessToken))
    } catch (caught) {
      setError(asApiError(caught))
    }
  }, [accessToken])

  const upload = useCallback(
    async (file: File) => {
      if (!accessToken) return

      setUploading(true)
      setError(null)
      try {
        // Sequential because each step needs the one before it: the presigned
        // fields come from the first call, and the document cannot be queued
        // until the bytes are actually in S3.
        const permission = await requestUpload(file.name, accessToken)
        await uploadToS3(permission.upload_url, permission.fields, file)
        await completeUpload(permission.document_id, accessToken)

        // Refresh rather than appending the returned row: a re-upload reuses
        // an existing document, so appending would show the same file twice.
        await refresh()
      } catch (caught) {
        setError(asApiError(caught))
      } finally {
        setUploading(false)
      }
    },
    [accessToken, refresh],
  )

  const remove = useCallback(
    async (documentId: string) => {
      if (!accessToken) return

      setError(null)
      try {
        await deleteDocument(documentId, accessToken)
        // Dropped locally as well as refetched, so the row disappears on the
        // click rather than after the next round trip.
        setDocuments((current) => current.filter((document) => document.id !== documentId))
        await refresh()
      } catch (caught) {
        setError(asApiError(caught))
      }
    },
    [accessToken, refresh],
  )

  // One initial read, so a returning researcher sees their library without
  // having to upload something first.
  //
  // The state is set inside refresh() after an await, not synchronously during
  // the effect, but the rule cannot see across the async boundary. Fetching on
  // mount is the intended use of an effect: synchronizing with an external
  // system.
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    if (accessToken) void refresh()
  }, [accessToken, refresh])

  const anyInProgress = documents.some((document) =>
    IN_PROGRESS_STATUSES.includes(document.status),
  )

  useEffect(() => {
    // Only while the worker still owes an answer. Polling an idle library
    // forever would keep every open tab generating requests for nothing.
    if (!anyInProgress || !accessToken) return

    const timer = setInterval(() => void refresh(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [anyInProgress, accessToken, refresh])

  const clearError = useCallback(() => setError(null), [])

  return { documents, uploading, error, upload, remove, refresh, clearError }
}
