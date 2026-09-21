// App.tsx
// Composes the query loop: sign in, provide a key, ask a question, read the
// grounded answer. Owns the request lifecycle and which view is showing; the
// pieces below own their own inputs.
//
// Two separate credentials are in play and neither replaces the other: the
// Cognito session decides whose documents are searched, the Anthropic key
// decides whose account pays for the answer.

import { useRef, useState } from 'react'
import { useAuth } from 'react-oidc-context'
import './App.css'
import { askQuestion } from './api/client'
import { ApiError } from './api/types'
import type { AskResponse } from './api/types'
import { hostedSignOutUrl, isAuthConfigured } from './auth/oidcConfig'
import { AnswerPanel } from './components/AnswerPanel'
import { ApiKeyPanel } from './components/ApiKeyPanel'
import { DocumentList } from './components/DocumentList'
import { DocumentUpload } from './components/DocumentUpload'
import { ErrorBanner } from './components/ErrorBanner'
import { HelpPage } from './components/HelpPage'
import { QuestionForm } from './components/QuestionForm'
import { SignInPanel } from './components/SignInPanel'
import { useApiKey } from './hooks/useApiKey'
import { useDocuments } from './hooks/useDocuments'

/**
 * Upload limit shown before the API has had a chance to state its own.
 *
 * Only ever used for the hint text and the client-side pre-check; S3's
 * presigned policy is what actually enforces a limit, and it uses the server's
 * value whatever this says.
 */
const DEFAULT_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

const UNEXPECTED_ERROR = new ApiError(
  'unexpected_error',
  'Something went wrong. Try asking again.',
  true,
  0,
)

const SIGNED_OUT_ERROR = new ApiError(
  'missing_auth',
  'Your session has ended. Sign in again to continue.',
  false,
  401,
)

function App() {
  const auth = useAuth()
  const keyState = useApiKey()
  const library = useDocuments(auth.user?.access_token)
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
    // Read per question rather than once at render: a token refreshed mid-session
    // means the value captured at render time is already stale.
    const accessToken = auth.user?.access_token
    if (!accessToken) {
      setError(SIGNED_OUT_ERROR)
      return
    }

    inFlight.current?.abort()
    const controller = new AbortController()
    inFlight.current = controller

    setLastQuestion(question)
    setPending(true)
    setError(null)
    setAnswer(null)

    try {
      const result = await askQuestion(question, keyState.apiKey, accessToken, controller.signal)
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

  /**
   * Drop the local session, then hand off to Cognito to end its own.
   *
   * The key goes too: it belongs to the person signing out, and leaving it in
   * sessionStorage would hand it to whoever signs in next on this tab.
   */
  function handleSignOut() {
    keyState.clearKey()
    void auth.removeUser()
    window.location.href = hostedSignOutUrl()
  }

  // Reachable signed out on purpose: this is the page explaining how to get an
  // Anthropic key, which a researcher may well want to read first.
  if (showHelp) return <HelpPage onBack={() => setShowHelp(false)} />

  if (auth.isLoading) {
    return (
      <main>
        <p aria-live="polite">Checking your sign-in...</p>
      </main>
    )
  }

  if (!auth.isAuthenticated) {
    return (
      <main>
        <header>
          <h1>BioGent</h1>
          <p>Ask questions about your research documents and get grounded answers.</p>
        </header>

        <SignInPanel
          configured={isAuthConfigured}
          error={auth.error}
          onSignIn={() => void auth.signinRedirect()}
          onOpenHelp={() => setShowHelp(true)}
        />
      </main>
    )
  }

  return (
    <main>
      <header>
        <h1>BioGent</h1>
        <p>Ask questions about your research documents and get grounded answers.</p>
        <p className="hint">
          Signed in as {auth.user?.profile.email ?? 'your account'}.{' '}
          <button type="button" className="link" onClick={handleSignOut}>
            Sign out
          </button>
        </p>
      </header>

      <ApiKeyPanel keyState={keyState} onOpenHelp={() => setShowHelp(true)} />

      <DocumentUpload
        onUpload={(file) => void library.upload(file)}
        uploading={library.uploading}
        maxBytes={DEFAULT_MAX_UPLOAD_BYTES}
      />
      {/* Its own banner rather than the shared one below: a failed upload and
          a failed question are unrelated, and routing both through one slot
          would let either wipe the other's message off the screen. */}
      <ErrorBanner
        error={library.error}
        onRetry={() => void library.refresh()}
        onUpdateKey={handleUpdateKey}
        onOpenHelp={() => setShowHelp(true)}
        onSignIn={() => void auth.signinRedirect()}
      />
      <DocumentList
        documents={library.documents}
        onRemove={(documentId) => void library.remove(documentId)}
      />

      <QuestionForm disabled={!keyState.hasKey} pending={pending} onSubmit={runQuestion} />
      <ErrorBanner
        error={error}
        onRetry={() => runQuestion(lastQuestion)}
        onUpdateKey={handleUpdateKey}
        onOpenHelp={() => setShowHelp(true)}
        onSignIn={() => void auth.signinRedirect()}
      />
      <AnswerPanel pending={pending} answer={answer} />
    </main>
  )
}

export default App
