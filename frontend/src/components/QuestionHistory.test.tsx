// QuestionHistory.test.tsx
// The list of earlier questions: choosing one, removing one, and marking which
// is currently on screen.

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { QuestionRecord } from '../api/types'
import { QuestionHistory } from './QuestionHistory'

function entry(id: string, question: string): QuestionRecord {
  return { id, question, answer: `Answer to ${question}`, sources: [], created_at: '2026-09-21T12:00:00Z' }
}

const ENTRIES = [entry('q-2', 'Where is PIEZO expressed?'), entry('q-1', 'What does PIEZO do?')]

function renderHistory(overrides = {}) {
  const props = {
    entries: ENTRIES,
    selectedId: null,
    onSelect: vi.fn(),
    onRemove: vi.fn(),
    ...overrides,
  }
  render(<QuestionHistory {...props} />)
  return props
}

describe('QuestionHistory', () => {
  it('renders nothing before anything has been asked', () => {
    const { container } = render(
      <QuestionHistory entries={[]} selectedId={null} onSelect={vi.fn()} onRemove={vi.fn()} />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('lists every earlier question, in the order given', () => {
    renderHistory()

    const questions = screen
      .getAllByRole('button')
      .filter((button) => !button.textContent?.startsWith('Remove'))
      .map((button) => button.textContent)

    expect(questions).toEqual(['Where is PIEZO expressed?', 'What does PIEZO do?'])
  })

  it('hands back the chosen entry', async () => {
    const user = userEvent.setup()
    const props = renderHistory()

    await user.click(screen.getByRole('button', { name: 'What does PIEZO do?' }))

    expect(props.onSelect).toHaveBeenCalledWith(ENTRIES[1])
  })

  it('removes the entry the button belongs to', async () => {
    // By accessible name: two identical "Remove" buttons would let a
    // positional test pass while removing the wrong question.
    const user = userEvent.setup()
    const props = renderHistory()

    await user.click(screen.getByRole('button', { name: /remove "what does piezo do\?"/i }))

    expect(props.onRemove).toHaveBeenCalledWith('q-1')
  })

  it('marks the entry currently on screen', () => {
    renderHistory({ selectedId: 'q-1' })

    expect(screen.getByRole('button', { name: 'What does PIEZO do?' })).toHaveAttribute(
      'aria-current',
      'true',
    )
    expect(
      screen.getByRole('button', { name: 'Where is PIEZO expressed?' }),
    ).not.toHaveAttribute('aria-current')
  })
})
