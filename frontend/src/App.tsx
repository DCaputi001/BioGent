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
import type { QuestionRecord } from './api/types'
import { hostedSignOutUrl, isAuthConfigured } from './auth/oidcConfig'
import { AnswerPanel } from './components/AnswerPanel'
import type { ShownAnswer } from './components/AnswerPanel'
import { ApiKeyPanel } from './components/ApiKeyPanel'
import { DocumentList } from './components/DocumentList'
import { DocumentUpload } from './components/DocumentUpload'
import { ErrorBanner } from './components/ErrorBanner'
import { HelpPage } from './components/HelpPage'
import { Mascot } from './components/Mascot'
import { QuestionForm } from './components/QuestionForm'
import { QuestionHistory } from './components/QuestionHistory'
import { SignInPanel } from './components/SignInPanel'
import { SpectrumRing } from './components/SpectrumRing'
import { Wordmark } from './components/Wordmark'
import { useApiKey } from './hooks/useApiKey'
import { useDocuments } from './hooks/useDocuments'
import { useQuestionHistory } from './hooks/useQuestionHistory'

/** The answer panel's contents, plus which history entry it came from, if any. */
interface Shown extends ShownAnswer {
  id: string | null
}

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
  const history = useQuestionHistory(auth.user?.access_token)
  const [showHelp, setShowHelp] = useState(false)
  const [pending, setPending] = useState(false)
  // Either the latest answer or one brought back from history. The id ties it
  // to a history entry so the list can mark which one is on screen.
  const [answer, setAnswer] = useState<Shown | null>(null)
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
      setAnswer({ id: result.id, question, answer: result.answer, sources: result.sources })

      // A null id means the answer arrived but could not be saved. It is still
      // shown; it just does not join a history it is not actually part of.
      if (result.id) {
        history.add({
          id: result.id,
          question,
          answer: result.answer,
          sources: result.sources,
          created_at: new Date().toISOString(),
        })
      }
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

  function showFromHistory(entry: QuestionRecord) {
    // Abandons any question still in flight: its answer would otherwise land
    // afterwards and replace the one the researcher just chose to look at.
    inFlight.current?.abort()
    setPending(false)
    setError(null)
    setAnswer({ id: entry.id, question: entry.question, answer: entry.answer, sources: entry.sources })
  }

  async function removeFromHistory(questionId: string) {
    await history.remove(questionId)
    // Clear the panel if it was showing the entry just removed, rather than
    // leaving something on screen the history no longer has.
    setAnswer((current) => (current?.id === questionId ? null : current))
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
      <main className="centered">
        <p className="status-line" aria-live="polite">
          <SpectrumRing size="1.25rem" spinning />
          Checking your sign-in...
        </p>
      </main>
    )
  }

  if (!auth.isAuthenticated) {
    return (
      <main className="welcome">
        <Mascot width={168} className="welcome-mark" />
        <Wordmark as="h1" className="welcome-wordmark" />

        <SignInPanel
          configured={isAuthConfigured}
          error={auth.error}
          onSignIn={() => void auth.signinRedirect()}
          onOpenHelp={() => setShowHelp(true)}
        />
      </main>
    )
  }

  // The actions every error banner can offer. The retry differs per banner,
  // since each retries its own request; these do not.
  const remedies = {
    onUpdateKey: handleUpdateKey,
    onOpenHelp: () => setShowHelp(true),
    onSignIn: () => void auth.signinRedirect(),
  }

  return (
    <div className="shell">
      <header className="topbar">
        <Wordmark as="h1" />
        <div className="account">
          <span className="account-email">{auth.user?.profile.email ?? 'your account'}</span>
          <button type="button" className="button-quiet" onClick={handleSignOut}>
            Sign out
          </button>
        </div>
      </header>

      {/* The reading pane comes first in the document as well as on screen,
          so keyboard and screen-reader order match what a researcher sees. */}
      <div className="workspace">
        <main className="reading">
          <ApiKeyPanel keyState={keyState} onOpenHelp={() => setShowHelp(true)} />
          <QuestionForm disabled={!keyState.hasKey} pending={pending} onSubmit={runQuestion} />
          <ErrorBanner error={error} onRetry={() => runQuestion(lastQuestion)} {...remedies} />
          <AnswerPanel pending={pending} answer={answer} />
        </main>

        <aside className="rail" aria-label="Your library">
          <DocumentUpload
            onUpload={(file) => void library.upload(file)}
            uploading={library.uploading}
            maxBytes={DEFAULT_MAX_UPLOAD_BYTES}
          />
          {/* Its own banner rather than the reading pane's: a failed upload and
              a failed question are unrelated, and sharing one slot would let
              either wipe the other's message off the screen. */}
          <ErrorBanner
            error={library.error}
            onRetry={() => void library.refresh()}
            {...remedies}
          />
          <DocumentList
            documents={library.documents}
            onRemove={(documentId) => void library.remove(documentId)}
          />

          <QuestionHistory
            entries={history.entries}
            selectedId={answer?.id ?? null}
            onSelect={showFromHistory}
            onRemove={(questionId) => void removeFromHistory(questionId)}
          />
          <ErrorBanner
            error={history.error}
            onRetry={() => void history.refresh()}
            {...remedies}
          />
        </aside>
      </div>
    </div>
  )
}

export default App
