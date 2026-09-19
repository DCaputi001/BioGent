// oidcConfig.ts
// OIDC settings for signing in against the Cognito Hosted UI, plus the sign-out
// URL that OIDC discovery does not cover. Read once at module load from the
// VITE_COGNITO_* build-time variables.
//
// None of these values is a secret. The client is a public SPA client with no
// secret at all, and every VITE_-prefixed variable is embedded in the built
// JavaScript in plain text regardless — which is exactly why no secret may ever
// be added to this file.

import type { AuthProviderProps } from 'react-oidc-context'

const AUTHORITY = import.meta.env.VITE_COGNITO_AUTHORITY ?? ''
const CLIENT_ID = import.meta.env.VITE_COGNITO_CLIENT_ID ?? ''
const HOSTED_UI_DOMAIN = import.meta.env.VITE_COGNITO_HOSTED_UI_DOMAIN ?? ''

/**
 * Whether sign-in can work at all in this build.
 *
 * A build with these unset would otherwise fail at the redirect with an opaque
 * Cognito error page; checking here lets the app say what is actually wrong.
 */
export const isAuthConfigured = Boolean(AUTHORITY && CLIENT_ID)

/** Where Cognito sends the browser back to. Must exactly match a callback URL. */
function redirectUri(): string {
  return `${window.location.origin}/`
}

export const oidcConfig: AuthProviderProps = {
  authority: AUTHORITY,
  client_id: CLIENT_ID,
  redirect_uri: redirectUri(),
  response_type: 'code',
  scope: 'openid email profile',

  // The authorization code and state land in the URL as query parameters. Left
  // alone they stay in the address bar and in history, and a reload would
  // re-submit an already-used code, which fails.
  onSigninCallback: () => {
    window.history.replaceState({}, document.title, window.location.pathname)
  },
}

/**
 * The Cognito Hosted UI sign-out URL.
 *
 * Built by hand because signing out is not part of OIDC discovery: clearing
 * local tokens alone would leave the Cognito session cookie intact, so the next
 * sign-in would silently skip the login form and look like it never signed out.
 */
export function hostedSignOutUrl(): string {
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    logout_uri: redirectUri(),
  })
  return `${HOSTED_UI_DOMAIN}/logout?${params.toString()}`
}
