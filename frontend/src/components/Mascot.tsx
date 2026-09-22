// Mascot.tsx
// The BioGent character: a figure drawn as a UMAP-style scatter of points,
// which is what a set of document embeddings looks like when it is plotted.
//
// Shown only where there is room to see it -- the welcome screen and the empty
// answer pane. At header size the scatter turns to noise, which is why the
// header and the favicon use the ring instead.

// Native aspect ratio of the exported artwork (frontend/public/brand).
const ASPECT = 849 / 518

interface MascotProps {
  /** Rendered width in CSS pixels; the height follows the artwork. */
  width: number
  className?: string
}

export function Mascot({ width, className = '' }: MascotProps) {
  return (
    <img
      className={className}
      src="/brand/mark-480.webp"
      // Width descriptors are the files' real pixel widths, so the browser can
      // pick the smallest one that is still sharp at this size and density.
      srcSet="/brand/mark-240.webp 146w, /brand/mark-480.webp 293w, /brand/mark-full.webp 518w"
      sizes={`${width}px`}
      width={width}
      height={Math.round(width * ASPECT)}
      // Decorative: every place it appears names the product or the action in
      // text, so describing the drawing would only add noise.
      alt=""
      decoding="async"
    />
  )
}
