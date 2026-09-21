// DocumentUpload.test.tsx
// The client-side pre-check and the picker.
//
// The pre-check is not the real enforcement -- S3's presigned policy is, and
// it applies whatever the browser does. What these cover is that a fixable
// mistake produces an immediate sentence instead of a round trip that ends in
// a rejection the researcher has to interpret.

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { DocumentUpload } from './DocumentUpload'

const MAX_BYTES = 50 * 1024 * 1024

function renderUpload(overrides = {}) {
  const props = { onUpload: vi.fn(), uploading: false, maxBytes: MAX_BYTES, ...overrides }
  render(<DocumentUpload {...props} />)
  return props
}

function fileOfSize(name: string, bytes: number): File {
  const file = new File(['x'], name, { type: 'application/pdf' })
  // File.size is read-only, so it is redefined rather than assigned -- the
  // alternative is allocating a real 50MB buffer in a unit test.
  Object.defineProperty(file, 'size', { value: bytes })
  return file
}

describe('DocumentUpload', () => {
  it('uploads an acceptable file', async () => {
    const user = userEvent.setup()
    const props = renderUpload()

    await user.upload(screen.getByLabelText(/choose a file/i), fileOfSize('paper.pdf', 1024))

    expect(props.onUpload).toHaveBeenCalledWith(expect.any(File))
  })

  it('refuses a file type ingestion cannot read, without asking for an upload URL', async () => {
    // applyAccept: false because the accept attribute only filters what the
    // picker offers by default -- a researcher can still choose "All files",
    // and a drag-and-drop ignores accept entirely. Left at its default, this
    // test would pass without the component's check existing at all.
    const user = userEvent.setup({ applyAccept: false })
    const props = renderUpload()

    await user.upload(screen.getByLabelText(/choose a file/i), fileOfSize('virus.exe', 1024))

    expect(props.onUpload).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot be read/i)
  })

  it('refuses a file over the limit before it is sent anywhere', async () => {
    const user = userEvent.setup()
    const props = renderUpload()

    await user.upload(
      screen.getByLabelText(/choose a file/i),
      fileOfSize('huge.pdf', MAX_BYTES + 1),
    )

    expect(props.onUpload).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/larger than/i)
  })

  it('refuses an empty file, which would ingest as nothing', async () => {
    const user = userEvent.setup()
    const props = renderUpload()

    await user.upload(screen.getByLabelText(/choose a file/i), fileOfSize('empty.pdf', 0))

    expect(props.onUpload).not.toHaveBeenCalled()
    expect(await screen.findByRole('alert')).toHaveTextContent(/empty/i)
  })

  it('accepts .txt and .md as well as .pdf', async () => {
    const user = userEvent.setup()
    const props = renderUpload()

    await user.upload(screen.getByLabelText(/choose a file/i), fileOfSize('notes.md', 500))

    expect(props.onUpload).toHaveBeenCalled()
  })

  it('judges the type case-insensitively', async () => {
    // A file from Windows is as likely to be PAPER.PDF as paper.pdf.
    const user = userEvent.setup()
    const props = renderUpload()

    await user.upload(screen.getByLabelText(/choose a file/i), fileOfSize('PAPER.PDF', 500))

    expect(props.onUpload).toHaveBeenCalled()
  })

  it('disables the picker while an upload is in flight', () => {
    renderUpload({ uploading: true })

    expect(screen.getByLabelText(/choose a file/i)).toBeDisabled()
    expect(screen.getByText(/uploading/i)).toBeInTheDocument()
  })

  it('states the limit and the accepted types up front', () => {
    // Cheaper to read than to discover by having an upload rejected.
    renderUpload()

    expect(screen.getByText(/50MB/)).toBeInTheDocument()
    expect(screen.getByText(/\.pdf/)).toBeInTheDocument()
  })

  it('reassures the researcher that uploads are private', () => {
    renderUpload()

    expect(screen.getByText(/only you can see/i)).toBeInTheDocument()
  })
})
