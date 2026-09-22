// AnswerPanel.tsx
// The reading pane's main content: an answer, the question it answers, and the
// papers it came from -- or the waiting state, or an invitation to ask.

import { Mascot } from './Mascot'
import { SpectrumRing } from './SpectrumRing'

/**
 * What the panel shows: the latest answer, or one brought back from history.
 *
 * Carries the question as well as the answer. With one answer on screen at a
 * time the question was obvious; once a researcher can pull up an older one,
 * an answer without its question is ambiguous.
 */
export interface ShownAnswer {
  question: string
  answer: string
  sources: string[]
}

interface AnswerPanelProps {
  pending: boolean
  answer: ShownAnswer | null
}

export function AnswerPanel({ pending, answer }: AnswerPanelProps) {
  if (pending) {
    return (
      <section className="answer-state" aria-live="polite">
        <p className="status-line">
          <SpectrumRing size="1.5rem" spinning />
          Searching your documents...
        </p>
        {/* The first question after the service starts loads the embedding
            model, which takes several seconds. Saying so prevents it reading
            as a hang. */}
        <p className="hint">The first question can take a little longer.</p>
      </section>
    )
  }

  if (!answer) {
    return (
      <section className="answer-empty">
        <Mascot width={96} className="answer-empty-mark" />
        <p>
          Answers appear here, drawn only from the papers in your library, with the sources
          they came from.
        </p>
      </section>
    )
  }

  return (
    <article className="answer" aria-live="polite">
      <h2 className="answer-question">{answer.question}</h2>
      {/* Set in the reading serif: an answer is prose to be read closely, not
          interface to be scanned. pre-wrap keeps the model's paragraph breaks,
          which would otherwise collapse into one block. */}
      <p className="answer-text">{answer.answer}</p>

      {answer.sources.length > 0 && (
        <section className="sources" aria-labelledby="sources-heading">
          <h3 id="sources-heading">Sources</h3>
          <ul>
            {answer.sources.map((source) => (
              <li key={source}>{source}</li>
            ))}
          </ul>
        </section>
      )}
    </article>
  )
}
