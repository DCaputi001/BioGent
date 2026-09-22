// useQuestionHistory.ts
// Holds the researcher's past questions: loads them on sign-in, adds each new
// answer as it arrives, and removes entries on request.
//
// The same shape as useDocuments -- a plain data hook that takes the access
// token, so a test can drive it without an OIDC provider and App composes views
// rather than knowing every HTTP call.

import { useCallback, useEffect, useState } from 'react'
import { deleteQuestion, listQuestions } from '../api/client'
import { ApiError } from '../api/types'
import type { QuestionRecord } from '../api/types'

const UNEXPECTED_ERROR = new ApiError(
  'unexpected_error',
  'Something went wrong with your question history.',
  true,
  0,
)

export interface QuestionHistoryState {
  entries: QuestionRecord[]
  error: ApiError | null
  /** Put a just-answered question at the top, without a round trip. */
  add: (entry: QuestionRecord) => void
  remove: (questionId: string) => Promise<void>
  refresh: () => Promise<void>
}

export function useQuestionHistory(accessToken: string | undefined): QuestionHistoryState {
  const [entries, setEntries] = useState<QuestionRecord[]>([])
  const [error, setError] = useState<ApiError | null>(null)

  const refresh = useCallback(async () => {
    if (!accessToken) return

    try {
      setEntries(await listQuestions(accessToken))
      setError(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : UNEXPECTED_ERROR)
    }
  }, [accessToken])

  // Added locally rather than refetched: the ask response already carries the
  // whole entry, so another request would only repeat what is on screen.
  // Filtered first so a retried question never shows up twice.
  const add = useCallback((entry: QuestionRecord) => {
    setEntries((current) => [entry, ...current.filter((existing) => existing.id !== entry.id)])
  }, [])

  const remove = useCallback(
    async (questionId: string) => {
      if (!accessToken) return

      try {
        await deleteQuestion(questionId, accessToken)
        setEntries((current) => current.filter((entry) => entry.id !== questionId))
        setError(null)
      } catch (caught) {
        setError(caught instanceof ApiError ? caught : UNEXPECTED_ERROR)
      }
    },
    [accessToken],
  )

  // Loaded on sign-in, so a returning researcher finds their earlier
  // questions waiting. The state is set inside refresh() after an await, not
  // synchronously during the effect -- the rule cannot see across that.
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    if (accessToken) void refresh()
  }, [accessToken, refresh])

  return { entries, error, add, remove, refresh }
}
