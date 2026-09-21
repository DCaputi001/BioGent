// DocumentUpload.tsx
// Where a researcher adds a paper to their own library: a drop zone with a
// file picker behind it.
//
// Both, not just the drop zone. Drag-and-drop is unusable with a keyboard or a
// screen reader, and on a phone there is nothing to drag from, so the picker
// is the real control and the drop zone is the shortcut.

import { useRef, useState } from 'react'

/** Must match storage.SUPPORTED_SUFFIXES -- anything else ingests as nothing. */
const ACCEPTED_SUFFIXES = ['.pdf', '.txt', '.md']

interface DocumentUploadProps {
  onUpload: (file: File) => void
  uploading: boolean
  /** From the API's UploadResponse; the limit S3 itself enforces. */
  maxBytes: number
  disabled?: boolean
}

function isAccepted(file: File): boolean {
  return ACCEPTED_SUFFIXES.some((suffix) => file.name.toLowerCase().endsWith(suffix))
}

function describeSize(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))}MB`
}

export function DocumentUpload({
  onUpload,
  uploading,
  maxBytes,
  disabled = false,
}: DocumentUploadProps) {
  const [dragging, setDragging] = useState(false)
  const [rejection, setRejection] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  /**
   * Refuse what we can see is wrong before asking for an upload URL.
   *
   * Not the real enforcement -- S3's presigned policy is, and it applies
   * whatever the browser does. This just turns a fixable mistake into an
   * immediate sentence instead of a round trip that ends in a rejection.
   */
  function reasonToRefuse(file: File): string | null {
    if (!isAccepted(file)) {
      return `${file.name} cannot be read. Upload a ${ACCEPTED_SUFFIXES.join(', ')} file.`
    }
    if (file.size > maxBytes) {
      return `${file.name} is larger than the ${describeSize(maxBytes)} limit.`
    }
    if (file.size === 0) {
      return `${file.name} is empty.`
    }
    return null
  }

  function handleFiles(files: FileList | null) {
    const file = files?.[0]
    if (!file) return

    const refusal = reasonToRefuse(file)
    setRejection(refusal)
    if (!refusal) onUpload(file)

    // Cleared so choosing the same file again after a failure still fires a
    // change event -- the input keeps its value otherwise and nothing happens.
    if (inputRef.current) inputRef.current.value = ''
  }

  const busy = uploading || disabled

  return (
    <section className="panel">
      <h2>Your documents</h2>

      <div
        className={dragging ? 'dropzone dropzone-active' : 'dropzone'}
        onDragOver={(event) => {
          // Without preventDefault the browser navigates to the file instead.
          event.preventDefault()
          if (!busy) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          if (!busy) handleFiles(event.dataTransfer.files)
        }}
      >
        <p>{uploading ? 'Uploading...' : 'Drop a paper here, or'}</p>

        {/* The real control. Visually plain, but reachable by keyboard and
            announced by a screen reader, which the drop zone is not -- so it
            carries a real label rather than relying on the text above it. */}
        <label htmlFor="document-file">Choose a file</label>
        <input
          id="document-file"
          ref={inputRef}
          type="file"
          accept={ACCEPTED_SUFFIXES.join(',')}
          disabled={busy}
          onChange={(event) => handleFiles(event.target.files)}
        />

        <p className="hint">
          {ACCEPTED_SUFFIXES.join(', ')} up to {describeSize(maxBytes)}. Only you can see
          what you upload.
        </p>
      </div>

      {rejection && (
        <p className="error" role="alert">
          {rejection}
        </p>
      )}
    </section>
  )
}
