// App.tsx
// Composes the query loop: provide a key, ask a question, read the grounded
// answer. Owns the request lifecycle and which view is showing; the pieces
// below own their own inputs.

import { useRef, useState } from 'react'
import './App.css'
import { askQuestion } from './api/client'
import { ApiError } from './api/types'
import type { AskResponse } from './api/types'
import { AnswerPanel } from './components/AnswerPanel'
import { ApiKeyPanel } from './components/ApiKeyPanel'
import { ErrorBanner } from './components/ErrorBanner'
import { HelpPage } from './components/HelpPage'
import { QuestionForm } from './components/QuestionForm'
import { useApiKey } from './hooks/useApiKey'

const UNEXPECTED_ERROR = new ApiError(
  'unexpected_error',
  'Something went wrong. Try asking again.',
  true,
  0,
)

function App() {
  const keyState = useApiKey()
  const [showHelp, setShowHelp] = useState(false)
  const [pending, setPending] = useState(false)
  const [answer, setAnswer] = useState<AskResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  // Kept so "try again" can re-send the same question without the researcher
  // retyping it; the form clears its own state on submit.
  const [lastQuestion, setLastQuestion] = useState('')
  // Lets a new question abandon the previous one: without this, a slow first
  // answer could land after a newer one and overwrite it.
  const inFlight = useRef<AbortController | null>(null)

  async function runQuestion(question: string) {
    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller

    setLastQuestion(question)
    setPending(true)
    setError(null)
    setAnswer(null)

    try {
      const result = await askQuestion(question, keyState.apiKey, controller.signal)
      setAnswer(result)
    } catch (caught) {
      // An abort means a newer question took over, so the UI belongs to that
      // request now and this one should leave the state alone.
      if (caught instanceof DOMException && caught.name === 'AbortError') return
      setError(caught instanceof ApiError ? caught : UNEXPECTED_ERROR)
    } finally {
      if (inFlight.current === controller) {
        setPending(false)
        inFlight.current = null
      }
    }
  }

  /** Clear the rejected key and put the researcher back at the key field. */
  function handleUpdateKey() {
    keyState.clearKey()
    setError(null)
    setAnswer(null)
  }

  if (showHelp) return <HelpPage onBack={() => setShowHelp(false)} />

  return (
    <main>
      <header>
        <h1>BioGent</h1>
        <p>Ask questions about your research documents and get grounded answers.</p>
      </header>

      <ApiKeyPanel keyState={keyState} onOpenHelp={() => setShowHelp(true)} />
      <QuestionForm disabled={!keyState.hasKey} pending={pending} onSubmit={runQuestion} />
      <ErrorBanner
        error={error}
        onRetry={() => runQuestion(lastQuestion)}
        onUpdateKey={handleUpdateKey}
        onOpenHelp={() => setShowHelp(true)}
      />
      <AnswerPanel pending={pending} answer={answer} />
    </main>
  )
}

export default App
