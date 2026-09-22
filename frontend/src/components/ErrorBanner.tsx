// ErrorBanner.tsx
// Shows a failed request and the one action worth taking about it.
//
// The wording comes from the backend (services/rag/app/errors.py), which
// already writes for a non-technical reader; this component adds only the
// affordance, chosen by remedyFor().

import { localHintFor, remedyFor } from '../api/errorActions'
import type { ApiError } from '../api/types'

const ANTHROPIC_BILLING_URL = 'https://console.anthropic.com/settings/billing'

interface ErrorBannerProps {
  error: ApiError | null
  onRetry: () => void
  onUpdateKey: () => void
  onOpenHelp: () => void
  onSignIn: () => void
}

export function ErrorBanner({
  error,
  onRetry,
  onUpdateKey,
  onOpenHelp,
  onSignIn,
}: ErrorBannerProps) {
  if (!error) return null

  const remedy = remedyFor(error)
  const hint = localHintFor(error)

  return (
    <section className="notice" role="alert">
      <p>{error.message}</p>
      {hint && <p className="hint">{hint}</p>}

      <div className="notice-actions">
        {remedy === 'fix-key' && (
          <>
            <button type="button" className="button-secondary" onClick={onUpdateKey}>
              Use a different key
            </button>
            <button type="button" className="button-link" onClick={onOpenHelp}>
              How do I get a key?
            </button>
          </>
        )}

        {remedy === 'add-credit' && (
          <a href={ANTHROPIC_BILLING_URL} target="_blank" rel="noreferrer noopener">
            Add credit in the Anthropic Console
          </a>
        )}

        {remedy === 'sign-in' && (
          <button type="button" className="button-secondary" onClick={onSignIn}>
            Sign in again
          </button>
        )}

        {remedy === 'retry' && (
          <button type="button" className="button-secondary" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </section>
  )
}
