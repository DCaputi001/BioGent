// QuestionHistory.tsx
// The researcher's earlier questions, newest first. Choosing one brings its
// answer back into the answer panel; each can be removed.

import type { QuestionRecord } from '../api/types'

interface QuestionHistoryProps {
  entries: QuestionRecord[]
  /** The entry currently shown in the answer panel, if it came from here. */
  selectedId: string | null
  onSelect: (entry: QuestionRecord) => void
  onRemove: (questionId: string) => void
}

// Date plus time, because several questions asked in one sitting would
// otherwise all read as the same day.
const WHEN = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

export function QuestionHistory({ entries, selectedId, onSelect, onRemove }: QuestionHistoryProps) {
  if (entries.length === 0) return null

  return (
    <section className="rail-section">
      <h2>Earlier questions</h2>
      <ul className="history">
        {entries.map((entry) => {
          const selected = entry.id === selectedId
          return (
            <li key={entry.id} className={selected ? 'history-item history-selected' : 'history-item'}>
              {/* A button, not a clickable list item, so it is reachable by
                  keyboard and announced as something that can be activated. */}
              <button
                type="button"
                className="history-question"
                aria-current={selected ? 'true' : undefined}
                onClick={() => onSelect(entry)}
              >
                {entry.question}
              </button>
              <div className="history-meta">
                <time dateTime={entry.created_at}>{WHEN.format(new Date(entry.created_at))}</time>
                <button
                  type="button"
                  className="button-remove"
                  onClick={() => onRemove(entry.id)}
                  aria-label={`Remove "${entry.question}" from your history`}
                >
                  Remove
                </button>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
