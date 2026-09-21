// DocumentList.test.tsx
// The library rows: what a researcher sees while waiting, and what they see
// when a document could not be read.
//
// The failed case is the one that matters. KNOWN_ISSUES.md's complaint was
// that a scanned PDF ingested as zero chunks with nothing saying why; these
// check the reason actually reaches the screen.

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { DocumentResponse } from '../api/types'
import { DocumentList } from './DocumentList'

function document(overrides: Partial<DocumentResponse> = {}): DocumentResponse {
  return {
    id: '11111111-2222-3333-4444-555555555555',
    filename: 'piezo-paper.pdf',
    status: 'ready',
    chunk_count: 12,
    error_message: null,
    ...overrides,
  }
}

describe('DocumentList', () => {
  it('invites a first upload when the library is empty', () => {
    render(<DocumentList documents={[]} onRemove={vi.fn()} />)

    expect(screen.getByText(/no documents yet/i)).toBeInTheDocument()
  })

  it('names each document and how far along it is', () => {
    render(<DocumentList documents={[document()]} onRemove={vi.fn()} />)

    expect(screen.getByText('piezo-paper.pdf')).toBeInTheDocument()
    expect(screen.getByText(/ready/i)).toBeInTheDocument()
  })

  it('describes progress in words rather than internal status names', () => {
    // "processing" is what the database calls it; it is not what someone
    // waiting on their document needs to read.
    render(<DocumentList documents={[document({ status: 'processing' })]} onRemove={vi.fn()} />)

    expect(screen.getByText(/reading it/i)).toBeInTheDocument()
    expect(screen.queryByText('processing')).not.toBeInTheDocument()
  })

  it("shows the backend's reason when a document failed", () => {
    render(
      <DocumentList
        documents={[
          document({
            status: 'failed',
            chunk_count: null,
            error_message: 'No readable text was found in this file.',
          }),
        ]}
        onRemove={vi.fn()}
      />,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('No readable text was found in this file.')
  })

  it('reports how much of a ready document was indexed', () => {
    render(<DocumentList documents={[document({ chunk_count: 154 })]} onRemove={vi.fn()} />)

    expect(screen.getByText(/154 sections indexed/i)).toBeInTheDocument()
  })

  it('removes the document the button belongs to', async () => {
    const user = userEvent.setup()
    const onRemove = vi.fn()
    const first = document({ id: 'first-id', filename: 'a.pdf' })
    const second = document({ id: 'second-id', filename: 'b.pdf' })
    render(<DocumentList documents={[first, second]} onRemove={onRemove} />)

    // By accessible name, not by position: two identical "Remove" buttons
    // would make a positional test pass while removing the wrong document.
    await user.click(screen.getByRole('button', { name: /remove b\.pdf/i }))

    expect(onRemove).toHaveBeenCalledWith('second-id')
  })

  it('announces status changes to a screen reader', () => {
    // The status changes on a poll, with nothing the researcher did to cause
    // it, so it has to be announced rather than only redrawn.
    render(<DocumentList documents={[document({ status: 'processing' })]} onRemove={vi.fn()} />)

    expect(screen.getByText(/reading it/i)).toHaveAttribute('aria-live', 'polite')
  })
})
