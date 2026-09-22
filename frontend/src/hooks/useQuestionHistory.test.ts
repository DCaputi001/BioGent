// useQuestionHistory.test.ts
// Loading, adding, and removing history entries, with the HTTP client mocked.

import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { deleteQuestion, listQuestions } from '../api/client'
import { ApiError } from '../api/types'
import type { QuestionRecord } from '../api/types'
import { useQuestionHistory } from './useQuestionHistory'

vi.mock('../api/client', () => ({
  listQuestions: vi.fn(),
  deleteQuestion: vi.fn(),
}))

const listQuestionsMock = vi.mocked(listQuestions)
const deleteQuestionMock = vi.mocked(deleteQuestion)
const TOKEN = 'header.payload.signature'

function entry(id: string, question = `Question ${id}`): QuestionRecord {
  return {
    id,
    question,
    answer: `Answer ${id}`,
    sources: [],
    created_at: '2026-09-21T12:00:00Z',
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  listQuestionsMock.mockResolvedValue([])
  deleteQuestionMock.mockResolvedValue(undefined)
})

describe('useQuestionHistory', () => {
  it('loads the researcher’s history on sign-in', async () => {
    listQuestionsMock.mockResolvedValue([entry('q-1'), entry('q-2')])

    const { result } = renderHook(() => useQuestionHistory(TOKEN))

    await waitFor(() => expect(result.current.entries).toHaveLength(2))
    expect(listQuestionsMock).toHaveBeenCalledWith(TOKEN)
  })

  it('does nothing without a session', () => {
    renderHook(() => useQuestionHistory(undefined))

    expect(listQuestionsMock).not.toHaveBeenCalled()
  })

  it('puts a new answer at the top without another request', async () => {
    listQuestionsMock.mockResolvedValue([entry('q-old')])
    const { result } = renderHook(() => useQuestionHistory(TOKEN))
    await waitFor(() => expect(result.current.entries).toHaveLength(1))
    listQuestionsMock.mockClear()

    act(() => result.current.add(entry('q-new')))

    expect(result.current.entries.map((e) => e.id)).toEqual(['q-new', 'q-old'])
    // The ask response already carried the entry; refetching would only
    // repeat what is on screen.
    expect(listQuestionsMock).not.toHaveBeenCalled()
  })

  it('never lists the same entry twice', async () => {
    const { result } = renderHook(() => useQuestionHistory(TOKEN))
    await waitFor(() => expect(listQuestionsMock).toHaveBeenCalled())

    act(() => result.current.add(entry('q-1')))
    act(() => result.current.add(entry('q-1')))

    expect(result.current.entries).toHaveLength(1)
  })

  it('removes an entry once the server confirms it', async () => {
    listQuestionsMock.mockResolvedValue([entry('q-1'), entry('q-2')])
    const { result } = renderHook(() => useQuestionHistory(TOKEN))
    await waitFor(() => expect(result.current.entries).toHaveLength(2))

    await act(async () => {
      await result.current.remove('q-1')
    })

    expect(deleteQuestionMock).toHaveBeenCalledWith('q-1', TOKEN)
    expect(result.current.entries.map((e) => e.id)).toEqual(['q-2'])
  })

  it('keeps an entry the server refused to remove', async () => {
    // Dropping it locally anyway would show a history that disagrees with the
    // server until the next reload brings it back.
    listQuestionsMock.mockResolvedValue([entry('q-1')])
    deleteQuestionMock.mockRejectedValue(
      new ApiError('document_store_unavailable', 'The library is unavailable.', true, 503),
    )
    const { result } = renderHook(() => useQuestionHistory(TOKEN))
    await waitFor(() => expect(result.current.entries).toHaveLength(1))

    await act(async () => {
      await result.current.remove('q-1')
    })

    expect(result.current.entries).toHaveLength(1)
    expect(result.current.error?.code).toBe('document_store_unavailable')
  })

  it('surfaces a failed load rather than showing an empty history', async () => {
    // An empty list would read as "you have never asked anything".
    listQuestionsMock.mockRejectedValue(
      new ApiError('invalid_token', 'Your session has expired.', false, 401),
    )

    const { result } = renderHook(() => useQuestionHistory(TOKEN))

    await waitFor(() => expect(result.current.error?.code).toBe('invalid_token'))
  })
})
