// AnswerPanel.tsx
// Renders the answer and the documents it came from, plus the waiting state.

import type { AskResponse } from '../api/types'

interface AnswerPanelProps {
  pending: boolean
  answer: AskResponse | null
}

export function AnswerPanel({ pending, answer }: AnswerPanelProps) {
  if (pending) {
    return (
      <section className="panel" aria-live="polite">
        <p>Searching your documents...</p>
        {/* The first question after the service starts loads the embedding
            model, which takes several seconds. Saying so prevents it reading
            as a hang. */}
        <p className="hint">The first question can take a little longer.</p>
      </section>
    )
  }

  if (!answer) return null

  return (
    <section className="panel" aria-live="polite">
      <h2>Answer</h2>
      {/* pre-wrap: the model's paragraph breaks are meaningful and would
          otherwise collapse into one block of text. */}
      <p className="answer">{answer.answer}</p>

      {answer.sources.length > 0 && (
        <>
          <h3>Sources</h3>
          <ul className="sources">
            {answer.sources.map((source) => (
              <li key={source}>{source}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}
