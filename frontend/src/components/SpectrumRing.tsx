// SpectrumRing.tsx
// The segmented spectral ring from the BioGent logo -- the "o" of the wordmark.
//
// One component does three jobs, which is what keeps the brand coherent: it is
// the letter in the wordmark, the indicator while an answer is being written,
// and the marker for a document still being read. The favicon
// (public/favicon.svg) draws the same geometry by hand, since a static file
// cannot import this.

// Clockwise from twelve o'clock, sampled from the logo's own ring.
const SEGMENTS = ['#55C32A', '#FCB907', '#FD9510', '#FF432D', '#F6429A', '#662BD1', '#0276EC']

const VIEWBOX = 32
const RADIUS = 12
const STROKE = 8
const CIRCUMFERENCE = 2 * Math.PI * RADIUS
// The thin gap between segments, in the same units as the circumference. The
// logo separates its colours with white hairlines rather than blending them.
const GAP = 1.4
const SEGMENT_LENGTH = CIRCUMFERENCE / SEGMENTS.length - GAP

interface SpectrumRingProps {
  /** Rendered size in CSS units; defaults to 1em so it scales with text. */
  size?: string
  /** Rotate continuously, as a progress indicator. Stilled by reduced-motion. */
  spinning?: boolean
  className?: string
}

export function SpectrumRing({ size = '1em', spinning = false, className = '' }: SpectrumRingProps) {
  const classes = ['spectrum-ring', spinning ? 'spectrum-ring-spinning' : '', className]
    .filter(Boolean)
    .join(' ')

  return (
    // Decorative: every place that uses it also says in words what is
    // happening, so a screen reader gets that rather than "image".
    <svg
      className={classes}
      width={size}
      height={size}
      viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}
      aria-hidden="true"
      focusable="false"
    >
      {SEGMENTS.map((colour, index) => (
        <circle
          key={colour}
          cx={VIEWBOX / 2}
          cy={VIEWBOX / 2}
          r={RADIUS}
          fill="none"
          stroke={colour}
          strokeWidth={STROKE}
          strokeDasharray={`${SEGMENT_LENGTH} ${CIRCUMFERENCE - SEGMENT_LENGTH}`}
          // Each segment starts where the previous one ended; the -90 turns
          // the start from three o'clock to twelve, matching the logo.
          transform={`rotate(${(index * 360) / SEGMENTS.length - 90} ${VIEWBOX / 2} ${VIEWBOX / 2})`}
        />
      ))}
    </svg>
  )
}
