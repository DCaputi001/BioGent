// ApiKeyPanel.tsx
// Where the researcher provides their own Anthropic API key, and the only
// place it is entered. Shows a masked confirmation once set, so the key is
// never rendered back to the screen in full.
//
// Two shapes on purpose. Before a key exists it is a setup step that has to be
// noticed; afterwards it is a single quiet line, because it no longer asks
// anything of the researcher.

import { useState } from 'react'
import type { ApiKeyState } from '../hooks/useApiKey'

/** Enough of the key to recognize it by, without displaying it. */
function maskKey(apiKey: string): string {
  return `****${apiKey.slice(-4)}`
}

interface ApiKeyPanelProps {
  keyState: ApiKeyState
  onOpenHelp: () => void
}

export function ApiKeyPanel({ keyState, onOpenHelp }: ApiKeyPanelProps) {
  const { apiKey, hasKey, saveKey, clearKey } = keyState
  const [draft, setDraft] = useState('')

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!draft.trim()) return
    saveKey(draft)
    // Drop the plaintext draft as soon as it is stored, so it is not sitting
    // in component state and in an input the browser may offer to autofill.
    setDraft('')
  }

  if (hasKey) {
    return (
      <div className="key-status">
        <p>
          Using your API key <code>{maskKey(apiKey)}</code>
        </p>
        <button type="button" className="button-link" onClick={clearKey}>
          Use a different key
        </button>
      </div>
    )
  }

  return (
    <section className="key-setup">
      <form onSubmit={handleSubmit}>
        <label htmlFor="api-key">Your Anthropic API key</label>
        <div className="inline-field">
          <input
            id="api-key"
            // type=password so the key is not readable over a shoulder or in a
            // screen share, and so browsers do not store it as form history.
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder="sk-ant-..."
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
          />
          <button type="submit" className="button-primary" disabled={!draft.trim()}>
            Save key
          </button>
        </div>
      </form>
      <p className="hint">
        Your key stays in this browser tab, is sent with each question, and is never stored on
        our servers.{' '}
        <button type="button" className="button-link" onClick={onOpenHelp}>
          How do I get a key?
        </button>
      </p>
    </section>
  )
}
