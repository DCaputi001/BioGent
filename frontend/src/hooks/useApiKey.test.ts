// useApiKey.test.ts
// Checks where the researcher's key is kept. The storage choice is a stated
// architecture decision, not an implementation detail: sessionStorage so it
// dies with the tab, never localStorage, which would leave it on disk.

import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useApiKey } from './useApiKey'

const KEY = 'sk-ant-test-key'

describe('useApiKey', () => {
  it('starts empty when nothing is stored', () => {
    const { result } = renderHook(() => useApiKey())

    expect(result.current.apiKey).toBe('')
    expect(result.current.hasKey).toBe(false)
  })

  it('keeps the key in sessionStorage and never in localStorage', () => {
    const { result } = renderHook(() => useApiKey())

    act(() => result.current.saveKey(KEY))

    expect(result.current.hasKey).toBe(true)
    expect(sessionStorage.getItem('biogent.anthropicApiKey')).toBe(KEY)
    expect(localStorage.getItem('biogent.anthropicApiKey')).toBeNull()
  })

  it('restores a key saved earlier in the session, so a reload does not retype it', () => {
    sessionStorage.setItem('biogent.anthropicApiKey', KEY)

    const { result } = renderHook(() => useApiKey())

    expect(result.current.apiKey).toBe(KEY)
  })

  it('clears the key from storage as well as from state', () => {
    const { result } = renderHook(() => useApiKey())
    act(() => result.current.saveKey(KEY))

    act(() => result.current.clearKey())

    expect(result.current.hasKey).toBe(false)
    expect(sessionStorage.getItem('biogent.anthropicApiKey')).toBeNull()
  })

  it('trims a pasted key, since a stray newline would be sent as part of it', () => {
    const { result } = renderHook(() => useApiKey())

    act(() => result.current.saveKey(`  ${KEY}\n`))

    expect(result.current.apiKey).toBe(KEY)
  })
})
