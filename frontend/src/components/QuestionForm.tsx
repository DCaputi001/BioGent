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
    <form className="panel" onSubmit={handleSubmit}>
      <label htmlFor="question">Ask a question about your documents</label>
      <textarea
        id="question"
        rows={3}
        value={question}
        disabled={disabled}
        placeholder="What role does PIEZO play in mechanosensation?"
        onChange={(event) => setQuestion(event.target.value)}
      />
      <button type="submit" disabled={disabled || pending || !question.trim()}>
        {pending ? 'Searching...' : 'Ask'}
      </button>
      {disabled && !pending && (
        <p className="hint">Add your API key above to start asking questions.</p>
      )}
    </form>
  )
}
