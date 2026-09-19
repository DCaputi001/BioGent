// errorActions.test.ts
// The remedy mapping, tested directly. A wrong answer here is the difference
// between offering a researcher a "try again" button that cannot possibly
// work and telling them what actually needs fixing.

import { describe, expect, it } from 'vitest'
import { localHintFor, remedyFor } from './errorActions'
import { ApiError } from './types'

function error(code: string, retryable: boolean, status = 400) {
  return new ApiError(code, 'message from the backend', retryable, status)
}

describe('remedyFor', () => {
  it.each(['invalid_api_key', 'missing_api_key', 'permission_denied'])(
    'treats %s as a key problem, not something to retry',
    (code) => {
      expect(remedyFor(error(code, false))).toBe('fix-key')
    },
  )

  it.each(['missing_auth', 'invalid_token'])(
    'treats %s as a session problem, not a key problem',
    (code) => {
      // Both of these arrive as 401s, exactly like a rejected Anthropic key.
      // Branching on status instead of code would send a researcher whose
      // session merely expired off to replace a key that is perfectly fine.
      expect(remedyFor(error(code, false, 401))).toBe('sign-in')
    },
  )

  it('sends an empty balance to billing rather than offering a retry', () => {
    expect(remedyFor(error('insufficient_credit', false, 402))).toBe('add-credit')
  })

  it.each(['rate_limited', 'upstream_unreachable', 'upstream_error', 'service_unreachable'])(
    'offers a retry for %s',
    (code) => {
      expect(remedyFor(error(code, true))).toBe('retry')
    },
  )

  it('offers a retry for an unknown code a newer backend might send', () => {
    expect(remedyFor(error('some_future_code', true))).toBe('retry')
  })

  it('offers nothing when the error is neither retryable nor fixable here', () => {
    expect(remedyFor(error('some_future_code', false))).toBe('none')
  })
})

describe('localHintFor', () => {
  it('names the command to start the API when the service is unreachable', () => {
    expect(localHintFor(error('service_unreachable', true, 0))).toContain('uvicorn')
  })

  it('adds nothing for errors whose cause is not local', () => {
    expect(localHintFor(error('invalid_api_key', false, 401))).toBeNull()
  })
})
