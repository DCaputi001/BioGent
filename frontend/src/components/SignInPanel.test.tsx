// SignInPanel.test.tsx
// The signed-out screen, including the case a researcher cannot fix: a build
// with no Cognito settings compiled into it.

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SignInPanel } from './SignInPanel'

function renderPanel(overrides = {}) {
  const props = {
    onSignIn: vi.fn(),
    onOpenHelp: vi.fn(),
    configured: true,
    ...overrides,
  }
  render(<SignInPanel {...props} />)
  return props
}

describe('SignInPanel', () => {
  it('invites the researcher to sign in', async () => {
    const user = userEvent.setup()
    const props = renderPanel()

    await user.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(props.onSignIn).toHaveBeenCalled()
  })

  it('explains an abandoned or failed sign-in rather than silently returning', async () => {
    renderPanel({ error: new Error('State mismatch in the redirect.') })

    expect(await screen.findByRole('alert')).toHaveTextContent('State mismatch in the redirect.')
  })

  it('names the missing build settings when sign-in cannot work at all', () => {
    // Without this the researcher would be sent to Cognito with no client id
    // and land on an opaque error page, with nothing pointing at the cause.
    renderPanel({ configured: false })

    expect(screen.getByRole('alert')).toHaveTextContent(/VITE_COGNITO_AUTHORITY/)
    expect(screen.queryByRole('button', { name: /^sign in$/i })).not.toBeInTheDocument()
  })
})
