import { useEffect, useRef, useState } from "react";

/**
 * Paint the low-res `preview` at once, then swap to the full-res `full` when it
 * has loaded (codebase-review finding #15). The stored original is ~4000×3000 — a
 * multi-second blank over cellular — while the 1600px preview arrives fast and,
 * fitted to the screen, looks the same. The fidelity rule governs what is STORED,
 * not what paints first: the reader still ends on the verbatim original.
 *
 * The full image is rendered immediately (so the browser starts fetching it) but
 * kept hidden until its own `load` fires; the preview shows until then. Exactly
 * one of the two is ever displayed, so a flex stage's single-image centring is
 * unchanged, and both are styled by the same `.viewer-stage img` rule.
 */
export function ProgressiveImage({
  preview,
  full,
  alt,
}: {
  preview: string;
  full: string;
  alt: string;
}) {
  const [loaded, setLoaded] = useState(false);
  const fullRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    // A new page: show its preview again, then wait for the new full image. If it
    // is already cached the `load` event can fire before React attaches onLoad, so
    // catch the already-complete case here rather than waiting for an event that
    // will never come.
    setLoaded(fullRef.current?.complete ?? false);
  }, [full]);

  return (
    <>
      <img
        ref={fullRef}
        src={full}
        alt={alt}
        onLoad={() => setLoaded(true)}
        style={loaded ? undefined : { display: "none" }}
      />
      {!loaded && <img src={preview} alt={alt} />}
    </>
  );
}
