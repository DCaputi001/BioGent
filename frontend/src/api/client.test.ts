// client.test.ts
// Tests the HTTP client against a stubbed fetch: no backend, no API key, no
// network. Focus is the parts that fail silently -- whether the key actually
// travels as a header, and whether every failure shape still yields a message
// a researcher can act on.

import { afterEach, describe, expect, it, vi } from 'vitest'
import { askQuestion } from './client'
import { ApiError } from './types'

const API_KEY = 'sk-ant-test-key'
const QUESTION = 'What role does PIEZO play in mechanosensation?'

// Typed with fetch's own parameters so mock.calls is a [url, init] tuple
// rather than an empty one, and the assertions below need no cast.
function mockFetch(response: Response) {
  const fetchMock = vi.fn((_url: string, _init: RequestInit) => Promise.resolve(response))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

/**
 * Separate from mockFetch on purpose: deciding resolve-vs-reject by
 * `instanceof Error` looks tidy but is wrong, because jsdom's DOMException
 * does not extend Error, so an abort would be handed back as a response.
 */
function mockFetchRejection(reason: unknown) {
  const fetchMock = vi.fn((_url: string, _init: RequestInit) => Promise.reject(reason))
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('askQuestion', () => {
  it('sends the key as a header and the question as JSON', async () => {
    const fetchMock = mockFetch(jsonResponse({ answer: 'PIEZO transduces force.', sources: [] }))

    await askQuestion(QUESTION, API_KEY)

    const [url, init] = fetchMock.mock.calls[0]
    const headers = init.headers as Record<string, string>

    expect(headers['X-Anthropic-Api-Key']).toBe(API_KEY)
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ question: QUESTION })
    // The key must never ride in the URL, where server logs and browser
    // history would capture it.
    expect(url).not.toContain(API_KEY)
    expect(url.endsWith('/ask')).toBe(true)
  })

  it('returns the answer and its sources', async () => {
    mockFetch(jsonResponse({ answer: 'PIEZO transduces force.', sources: ['piezo.pdf'] }))

    const result = await askQuestion(QUESTION, API_KEY)

    expect(result).toEqual({ answer: 'PIEZO transduces force.', sources: ['piezo.pdf'] })
  })

  it('turns the documented error body into a typed ApiError', async () => {
    mockFetch(
      jsonResponse(
        {
          error: {
            code: 'invalid_api_key',
            message: 'Anthropic rejected this API key.',
            retryable: false,
          },
        },
        401,
      ),
    )

    const error = await askQuestion(QUESTION, API_KEY).catch((caught) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('invalid_api_key')
    expect(error.message).toBe('Anthropic rejected this API key.')
    expect(error.retryable).toBe(false)
    expect(error.status).toBe(401)
  })

  it('still produces a usable message when the error body is not JSON', async () => {
    // What a proxy or CloudFront returns when it fails before reaching the app.
    mockFetch(new Response('<html>502 Bad Gateway</html>', { status: 502 }))

    const error = await askQuestion(QUESTION, API_KEY).catch((caught) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('unreadable_response')
    expect(error.message.length).toBeGreaterThan(0)
  })

  it('reports an unreachable service rather than throwing a raw network error', async () => {
    mockFetchRejection(new TypeError('Failed to fetch'))

    const error = await askQuestion(QUESTION, API_KEY).catch((caught) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('service_unreachable')
    expect(error.retryable).toBe(true)
  })

  it('lets an abort through untouched, so a superseded question stays silent', async () => {
    mockFetchRejection(new DOMException('The operation was aborted.', 'AbortError'))

    const error = await askQuestion(QUESTION, API_KEY).catch((caught) => caught)

    expect(error).toBeInstanceOf(DOMException)
    expect(error.name).toBe('AbortError')
  })
})
