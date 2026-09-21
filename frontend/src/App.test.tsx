// App.test.tsx
// End-to-end of the browser half of the loop, with the HTTP client mocked:
// provide a key, ask a question, see the answer and its sources. Also covers
// the two states a researcher is most likely to hit -- no key yet, and a key
// the API rejects.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useAuth } from 'react-oidc-context'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import {
  askQuestion,
  completeUpload,
  deleteQuestion,
  listDocuments,
  listQuestions,
  requestUpload,
  uploadToS3,
} from './api/client'
import { ApiError } from './api/types'

// The document functions are mocked too, not just askQuestion: App now mounts
// useDocuments, which reads the library on sign-in. Left out, every test here
// would fail inside the hook rather than on what it was actually checking.
vi.mock('./api/client', () => ({
  askQuestion: vi.fn(),
  requestUpload: vi.fn(),
  uploadToS3: vi.fn(),
  completeUpload: vi.fn(),
  listDocuments: vi.fn(),
  deleteDocument: vi.fn(),
  listQuestions: vi.fn(),
  deleteQuestion: vi.fn(),
}))
vi.mock('react-oidc-context', () => ({ useAuth: vi.fn() }))

// Stubbed because the real module reads VITE_COGNITO_* at import time, which
// are unset under test — the app would then correctly render its "sign-in is
// not configured" notice in place of every screen these tests exercise.
vi.mock('./auth/oidcConfig', () => ({
  isAuthConfigured: true,
  oidcConfig: {},
  hostedSignOutUrl: () => 'https://example.auth.us-east-1.amazoncognito.com/logout',
}))

const askQuestionMock = vi.mocked(askQuestion)
const useAuthMock = vi.mocked(useAuth)
const KEY = 'sk-ant-test-key'
const TOKEN = 'header.payload.signature'
const QUESTION = 'What role does PIEZO play in mechanosensation?'

/** The auth state for a researcher who is signed in and has a live token. */
function signedIn(overrides: Record<string, unknown> = {}) {
  return {
    isLoading: false,
    isAuthenticated: true,
    user: { access_token: TOKEN, profile: { email: 'researcher@example.org' } },
    error: undefined,
    signinRedirect: vi.fn(),
    removeUser: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  } as unknown as ReturnType<typeof useAuth>
}

async function provideKey(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/your anthropic api key/i), KEY)
  await user.click(screen.getByRole('button', { name: /save key/i }))
}

const listDocumentsMock = vi.mocked(listDocuments)
const listQuestionsMock = vi.mocked(listQuestions)

beforeEach(() => {
  askQuestionMock.mockReset()
  // An empty library by default, so tests about the question loop are not
  // also asserting on document rows they never set up.
  listDocumentsMock.mockReset()
  listDocumentsMock.mockResolvedValue([])
  // Likewise an empty history, so existing tests see today's single-answer UI.
  listQuestionsMock.mockReset()
  listQuestionsMock.mockResolvedValue([])
  vi.mocked(deleteQuestion).mockReset()
  vi.mocked(deleteQuestion).mockResolvedValue(undefined)
  vi.mocked(requestUpload).mockReset()
  vi.mocked(uploadToS3).mockReset()
  vi.mocked(completeUpload).mockReset()
  useAuthMock.mockReturnValue(signedIn())
})

describe('App', () => {
  it('cannot ask anything until a key is provided', () => {
    render(<App />)

    expect(screen.getByLabelText(/ask a question/i)).toBeDisabled()
    expect(screen.getByRole('button', { name: /ask/i })).toBeDisabled()
  })

  it('answers a question on the provided key and shows its sources', async () => {
    const user = userEvent.setup()
    askQuestionMock.mockResolvedValue({
      id: 'q-1',
      answer: 'PIEZO channels transduce mechanical force.',
      sources: ['piezo.pdf', 'mechanosensation.pdf'],
    })
    render(<App />)

    await provideKey(user)
    await user.type(screen.getByLabelText(/ask a question/i), QUESTION)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    expect(
      await screen.findByText('PIEZO channels transduce mechanical force.'),
    ).toBeInTheDocument()
    expect(screen.getByText('piezo.pdf')).toBeInTheDocument()
    expect(screen.getByText('mechanosensation.pdf')).toBeInTheDocument()
    // The key the researcher typed is the key the request carried.
    expect(askQuestionMock).toHaveBeenCalledWith(QUESTION, KEY, TOKEN, expect.any(AbortSignal))
  })

  it('masks the key once saved rather than displaying it back', async () => {
    const user = userEvent.setup()
    render(<App />)

    await provideKey(user)

    expect(screen.queryByText(KEY)).not.toBeInTheDocument()
    expect(screen.getByText(/\*\*\*\*-key/)).toBeInTheDocument()
  })

  it("shows the backend's message when a request fails", async () => {
    const user = userEvent.setup()
    askQuestionMock.mockRejectedValue(
      new ApiError('invalid_api_key', 'Anthropic rejected this API key.', false, 401),
    )
    render(<App />)

    await provideKey(user)
    await user.type(screen.getByLabelText(/ask a question/i), QUESTION)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Anthropic rejected this API key.')
  })

  it('lets a researcher replace a rejected key, clearing the stored one', async () => {
    const user = userEvent.setup()
    askQuestionMock.mockRejectedValue(
      new ApiError('invalid_api_key', 'Anthropic rejected this API key.', false, 401),
    )
    render(<App />)

    await provideKey(user)
    await user.type(screen.getByLabelText(/ask a question/i), QUESTION)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))
    // Scoped to the alert: the key panel offers the same action, and this test
    // is about the one attached to the error.
    const alert = await screen.findByRole('alert')
    await user.click(within(alert).getByRole('button', { name: /use a different key/i }))

    // Back to the key form, and the rejected key is gone from storage rather
    // than lingering to fail the next question the same way.
    expect(screen.getByLabelText(/your anthropic api key/i)).toBeInTheDocument()
    expect(sessionStorage.getItem('biogent.anthropicApiKey')).toBeNull()
  })

  it('offers no retry for an empty balance, since retrying cannot fix it', async () => {
    const user = userEvent.setup()
    askQuestionMock.mockRejectedValue(
      new ApiError('insufficient_credit', 'This account is out of credit.', false, 402),
    )
    render(<App />)

    await provideKey(user)
    await user.type(screen.getByLabelText(/ask a question/i), QUESTION)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    await screen.findByRole('alert')
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: /add credit/i })).toBeInTheDocument()
  })

  it('retries the same question without making the researcher retype it', async () => {
    const user = userEvent.setup()
    askQuestionMock.mockRejectedValueOnce(
      new ApiError('rate_limited', 'Anthropic is rate-limiting this key.', true, 429),
    )
    render(<App />)

    await provideKey(user)
    await user.type(screen.getByLabelText(/ask a question/i), QUESTION)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    askQuestionMock.mockResolvedValueOnce({
      id: 'q-2',
      answer: 'PIEZO transduces force.',
      sources: [],
    })
    await user.click(await screen.findByRole('button', { name: /try again/i }))

    expect(await screen.findByText('PIEZO transduces force.')).toBeInTheDocument()
    expect(askQuestionMock).toHaveBeenLastCalledWith(QUESTION, KEY, TOKEN, expect.any(AbortSignal))
  })

  it('tells a local user how to start the API when it is unreachable', async () => {
    const user = userEvent.setup()
    askQuestionMock.mockRejectedValue(
      new ApiError('service_unreachable', 'Could not reach the document service.', true, 0),
    )
    render(<App />)

    await provideKey(user)
    await user.type(screen.getByLabelText(/ask a question/i), QUESTION)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('uvicorn')
  })

  it('opens the onboarding page from the key panel and comes back', async () => {
    const user = userEvent.setup()
    render(<App />)

    await user.click(screen.getByRole('button', { name: /how do i get a key/i }))
    expect(screen.getByRole('heading', { name: /getting an anthropic api key/i })).toBeInTheDocument()
    // The trap worth surfacing: a key with no credit behind it.
    expect(screen.getByText(/a key on its own is not enough/i)).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: /back to questions/i })[0])
    expect(screen.getByLabelText(/your anthropic api key/i)).toBeInTheDocument()
  })
})

describe('App, signed out', () => {
  beforeEach(() => {
    useAuthMock.mockReturnValue(signedIn({ isAuthenticated: false, user: undefined }))
  })

  it('offers sign-in instead of the question form', () => {
    render(<App />)

    expect(screen.getByRole('button', { name: /^sign in$/i })).toBeInTheDocument()
    // The whole point of the gate: no route to asking anything without a session.
    expect(screen.queryByLabelText(/ask a question/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/your anthropic api key/i)).not.toBeInTheDocument()
  })

  it('starts the Cognito redirect when sign-in is clicked', async () => {
    const user = userEvent.setup()
    const auth = signedIn({ isAuthenticated: false, user: undefined })
    useAuthMock.mockReturnValue(auth)
    render(<App />)

    await user.click(screen.getByRole('button', { name: /^sign in$/i }))

    expect(auth.signinRedirect).toHaveBeenCalled()
  })

  it('still lets a researcher read how to get an Anthropic key', async () => {
    const user = userEvent.setup()
    render(<App />)

    // Deliberately reachable signed out: deciding whether to sign up at all is
    // easier after reading what the key costs and how to get one.
    await user.click(screen.getByRole('button', { name: /how do i get an anthropic api key/i }))

    expect(
      screen.getByRole('heading', { name: /getting an anthropic api key/i }),
    ).toBeInTheDocument()
  })

})

describe('App, document library', () => {
  it('uploads a paper and shows it once the worker has read it', async () => {
    // The whole Phase 8 loop through the UI: upload, watch the status move as
    // the worker gets to it, then ask something grounded in that document.
    const user = userEvent.setup()
    vi.mocked(requestUpload).mockResolvedValue({
      document_id: 'doc-1',
      filename: 'piezo.pdf',
      upload_url: 'https://bucket.s3.amazonaws.com/',
      fields: { key: 'users/sub/documents/piezo.pdf' },
      max_bytes: 52428800,
    })
    vi.mocked(uploadToS3).mockResolvedValue(undefined)
    vi.mocked(completeUpload).mockResolvedValue({
      id: 'doc-1',
      filename: 'piezo.pdf',
      status: 'processing',
      chunk_count: null,
      error_message: null,
    })
    // What the list returns after the upload: the worker has finished.
    listDocumentsMock.mockResolvedValue([
      { id: 'doc-1', filename: 'piezo.pdf', status: 'ready', chunk_count: 12, error_message: null },
    ])
    render(<App />)

    await user.upload(
      screen.getByLabelText(/choose a file/i),
      new File(['bytes'], 'piezo.pdf', { type: 'application/pdf' }),
    )

    expect(await screen.findByText('piezo.pdf')).toBeInTheDocument()
    expect(await screen.findByText(/ready/i)).toBeInTheDocument()
    expect(vi.mocked(uploadToS3)).toHaveBeenCalled()
  })

  it('shows why a document could not be read', async () => {
    listDocumentsMock.mockResolvedValue([
      {
        id: 'doc-2',
        filename: 'scan.pdf',
        status: 'failed',
        chunk_count: null,
        error_message: 'No readable text was found in this file.',
      },
    ])
    render(<App />)

    expect(
      await screen.findByText('No readable text was found in this file.'),
    ).toBeInTheDocument()
  })
})

describe('App, question history', () => {
  async function ask(user: ReturnType<typeof userEvent.setup>, question: string) {
    await user.type(screen.getByLabelText(/ask a question/i), question)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))
  }

  it('lets a researcher go back to an earlier answer', async () => {
    const user = userEvent.setup()
    askQuestionMock
      .mockResolvedValueOnce({ id: 'q-1', answer: 'First answer.', sources: ['a.pdf'] })
      .mockResolvedValueOnce({ id: 'q-2', answer: 'Second answer.', sources: ['b.pdf'] })
    render(<App />)
    await provideKey(user)

    await ask(user, 'What does PIEZO do?')
    await screen.findByText('First answer.')
    await ask(user, 'Where is it expressed?')
    await screen.findByText('Second answer.')
    // Asking replaced the first answer on screen, as it always has.
    expect(screen.queryByText('First answer.')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'What does PIEZO do?' }))

    expect(screen.getByText('First answer.')).toBeInTheDocument()
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
    expect(screen.queryByText('Second answer.')).not.toBeInTheDocument()
  })

  it('shows history from earlier sessions as soon as the researcher signs in', async () => {
    listQuestionsMock.mockResolvedValue([
      {
        id: 'q-old',
        question: 'A question from last week',
        answer: 'An answer from last week.',
        sources: ['old.pdf'],
        created_at: '2026-09-14T10:00:00Z',
      },
    ])
    render(<App />)

    expect(
      await screen.findByRole('button', { name: 'A question from last week' }),
    ).toBeInTheDocument()
  })

  it('clears the answer panel when the entry on screen is removed', async () => {
    // Leaving it up would show an answer the history no longer has.
    const user = userEvent.setup()
    listQuestionsMock.mockResolvedValue([
      {
        id: 'q-old',
        question: 'A question from last week',
        answer: 'An answer from last week.',
        sources: [],
        created_at: '2026-09-14T10:00:00Z',
      },
    ])
    render(<App />)

    await user.click(await screen.findByRole('button', { name: 'A question from last week' }))
    expect(screen.getByText('An answer from last week.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /remove "a question from last week"/i }))

    expect(vi.mocked(deleteQuestion)).toHaveBeenCalledWith('q-old', TOKEN)
    await waitFor(() =>
      expect(screen.queryByText('An answer from last week.')).not.toBeInTheDocument(),
    )
  })

  it('still shows an answer that could not be saved to history', async () => {
    // A null id means the history write failed server-side. The researcher
    // paid for the answer, so it is shown -- it just does not join the list.
    const user = userEvent.setup()
    askQuestionMock.mockResolvedValueOnce({ id: null, answer: 'Unsaved answer.', sources: [] })
    render(<App />)
    await provideKey(user)

    await ask(user, 'A question that will not be saved')

    expect(await screen.findByText('Unsaved answer.')).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'A question that will not be saved' }),
    ).not.toBeInTheDocument()
  })
})

describe('App, expired session', () => {
  it('offers sign-in again rather than telling the researcher to fix their key', async () => {
    const user = userEvent.setup()
    askQuestionMock.mockRejectedValue(
      new ApiError('invalid_token', 'Your session has expired.', false, 401),
    )
    render(<App />)

    await provideKey(user)
    await user.type(screen.getByLabelText(/ask a question/i), QUESTION)
    await user.click(screen.getByRole('button', { name: /^ask$/i }))

    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('button', { name: /sign in again/i })).toBeInTheDocument()
    // Both are 401s; offering the key remedy here would send them to fix the
    // wrong credential entirely.
    expect(
      within(alert).queryByRole('button', { name: /use a different key/i }),
    ).not.toBeInTheDocument()
  })

  it('shows who is signed in, with a way out', () => {
    render(<App />)

    expect(screen.getByText(/researcher@example\.org/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument()
  })
})
