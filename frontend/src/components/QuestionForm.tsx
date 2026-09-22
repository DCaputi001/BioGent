// QuestionForm.tsx
// The search box: a question, and a submit that stays disabled whenever
// sending would fail anyway (no key, empty question, request already running).

import { useState } from 'react'

interface QuestionFormProps {
  disabled: boolean
  pending: boolean
  onSubmit: (question: string) => void
}

export function QuestionForm({ disabled, pending, onSubmit }: QuestionFormProps) {
  const [question, setQuestion] = useState('')

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const trimmed = question.trim()
    // The API rejects a blank question with a 422; catching it here avoids a
    // pointless round trip and keeps the button honest.
    if (!trimmed || disabled || pending) return
    onSubmit(trimmed)
  }

  return (
    <form className="ask" onSubmit={handleSubmit}>
      <label htmlFor="question" className="ask-label">
        Ask a question about your documents
      </label>
      {/* The field and its button share one frame, so the action reads as part
          of the question rather than a separate control below it. */}
      <div className="ask-field">
        <textarea
          id="question"
          rows={3}
          value={question}
          disabled={disabled}
          placeholder="What role does PIEZO play in mechanosensation?"
          onChange={(event) => setQuestion(event.target.value)}
        />
        <div className="ask-actions">
          <button
            type="submit"
            className="button-primary"
            disabled={disabled || pending || !question.trim()}
          >
            {pending ? 'Searching...' : 'Ask'}
          </button>
        </div>
      </div>
      {disabled && !pending && (
        <p className="hint">Add your API key above to start asking questions.</p>
      )}
    </form>
  )
}
