// Wordmark.tsx
// "biogent" in live type, with the spectral ring standing in for the "o" as it
// does in the logo.
//
// Live text rather than the logo image, for two reasons: the logo's lettering
// is dark navy on transparent and would vanish in dark mode, and text stays
// sharp at every size where a bitmap would blur in a 56px header.

import { SpectrumRing } from './SpectrumRing'

interface WordmarkProps {
  /** A heading level for the page this sits on; a plain span otherwise. */
  as?: 'h1' | 'span'
  className?: string
}

export function Wordmark({ as: Tag = 'span', className = '' }: WordmarkProps) {
  return (
    <Tag className={`wordmark ${className}`.trim()}>
      {/* The visible letters are split around the ring, which would read as
          "bi gent" to a screen reader; the product name is given whole instead. */}
      <span aria-hidden="true" className="wordmark-letters">
        bi
        <SpectrumRing size="0.62em" className="wordmark-o" />
        gent
      </span>
      <span className="visually-hidden">BioGent</span>
    </Tag>
  )
}
