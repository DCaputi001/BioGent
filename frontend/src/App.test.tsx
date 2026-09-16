// App.test.tsx
// End-to-end of the browser half of the loop, with the HTTP client mocked:
// provide a key, ask a question, see the answer and its sources. Also covers
// the two states a researcher is most likely to hit -- no key yet, and a key
// the API rejects.

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { askQuestion } from './api/client'
import { ApiError } from './api/types'

vi.mock('./api/client', () => ({ askQuestion: vi.fn() }))

const askQuestionMock = vi.mocked(askQuestion)
const KEY = 'sk-ant-test-key'
const QUESTION = 'What role does PIEZO play in mechanosensation?'

async function provideKey(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/your anthropic api key/i), KEY)
  await user.click(screen.getByRole('button', { name: /save key/i }))
}

beforeEach(() => {
  askQuestionMock.mockReset()
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
    expect(askQuestionMock).toHaveBeenCalledWith(QUESTION, KEY, expect.any(AbortSignal))
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

    askQuestionMock.mockResolvedValueOnce({ answer: 'PIEZO transduces force.', sources: [] })
    await user.click(await screen.findByRole('button', { name: /try again/i }))

    expect(await screen.findByText('PIEZO transduces force.')).toBeInTheDocument()
    expect(askQuestionMock).toHaveBeenLastCalledWith(QUESTION, KEY, expect.any(AbortSignal))
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
