// SignInPanel.tsx
// The signed-out view: what BioGent is, and the button that starts sign-in.
// Rendered in place of the query UI until there is a session.

interface SignInPanelProps {
  onSignIn: () => void
  onOpenHelp: () => void
  /** A failed or abandoned sign-in attempt, if there was one. */
  error?: Error | null
  /** False when the build has no Cognito settings, which no researcher can fix. */
  configured: boolean
}

export function SignInPanel({ onSignIn, onOpenHelp, error, configured }: SignInPanelProps) {
  if (!configured) {
    return (
      <section className="notice signin" role="alert">
        <p>
          Sign-in is not configured in this build, so there is no way to reach your
          documents.
        </p>
        <p className="hint">
          If you are running this locally, set VITE_COGNITO_AUTHORITY and
          VITE_COGNITO_CLIENT_ID in frontend/.env.local from the Terraform outputs.
        </p>
      </section>
    )
  }

  return (
    <section className="signin">
      <p>
        Sign in to upload research documents and ask questions grounded in them. Your
        documents are visible only to you.
      </p>

      {error && (
        <p className="field-error" role="alert">
          That sign-in did not complete: {error.message}
        </p>
      )}

      <div className="signin-actions">
        <button type="button" className="button-primary button-large" onClick={onSignIn}>
          Sign in
        </button>
        <button type="button" className="button-link" onClick={onOpenHelp}>
          How do I get an Anthropic API key?
        </button>
      </div>

      <p className="hint">
        You will also need your own Anthropic API key to ask questions. You can read how
        to get one before signing in.
      </p>
    </section>
  )
}
