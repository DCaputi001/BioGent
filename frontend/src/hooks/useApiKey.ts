// useApiKey.ts
// Holds the researcher's Anthropic API key for the browser session.
//
// sessionStorage, deliberately: the key survives a page reload so a researcher
// is not retyping it after every question, but it is gone when the tab closes
// rather than sitting on disk indefinitely as localStorage would. It is never
// sent anywhere except the API request that needs it, and never to our server
// for storage -- see ARCHITECTURE.md, "Safe key handling".
//
// Constraint this relies on: anything in browser storage is readable by any
// script running on the page, so this app must not load third-party scripts.

import { useCallback, useState } from 'react'

const STORAGE_KEY = 'biogent.anthropicApiKey'

function readStoredKey(): string {
  try {
    return sessionStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    // Private-browsing modes can throw on storage access. An in-memory key
    // still works for the session; it just will not survive a reload.
    return ''
  }
}

export interface ApiKeyState {
  apiKey: string
  hasKey: boolean
  saveKey: (key: string) => void
  clearKey: () => void
}

export function useApiKey(): ApiKeyState {
  const [apiKey, setApiKey] = useState<string>(readStoredKey)

  const saveKey = useCallback((key: string) => {
    const trimmed = key.trim()
    setApiKey(trimmed)
    try {
      sessionStorage.setItem(STORAGE_KEY, trimmed)
    } catch {
      // Keeping it in memory is better than refusing to work at all.
    }
  }, [])

  const clearKey = useCallback(() => {
    setApiKey('')
    try {
      sessionStorage.removeItem(STORAGE_KEY)
    } catch {
      // Nothing to remove if storage was unavailable when saving.
    }
  }, [])

  return { apiKey, hasKey: apiKey.length > 0, saveKey, clearKey }
}
