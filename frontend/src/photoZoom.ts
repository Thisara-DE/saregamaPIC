/**
 * Zoom/pan maths for the correction editor's photo pane (codebase-review
 * finding #11 — the photo and the line being corrected were decoupled: a fixed
 * 38vh pane, no zoom, no way to bring a faint accidental closer).
 *
 * Pure and separate from React for the same reason as stfEdit/stfTranspose: the
 * pointer-event glue cannot be exercised in jsdom (no layout, no real pointer
 * geometry), but the arithmetic deciding where the photo ends up is exactly the
 * part that goes subtly wrong. All coordinates are CSS pixels in the pane's own
 * box. The image is drawn as `translate(x, y) scale(scale)` with
 * `transform-origin: 0 0`, so x/y are the position of the image's top-left
 * corner inside the pane.
 */

export type Transform = { scale: number; x: number; y: number };
export type Point = { x: number; y: number };

/**
 * The layout a transform is clamped against: the pane's visible box and the
 * image's UNTRANSFORMED size (its `offsetWidth`/`offsetHeight` — a CSS
 * transform does not change those, which is why they can be read at any zoom).
 */
export type Fit = { paneW: number; paneH: number; imageW: number; imageH: number };

// Scale 1 = the image fitted to the pane's width, which is how this pane has
// always looked. 6x is enough to settle a smudged octave dot on a phone without
// letting the reader get lost in the sheet.
export const MIN_SCALE = 1;
export const MAX_SCALE = 6;
export const STEP_FACTOR = 1.5; // one press of the - / + buttons
export const DOUBLE_TAP_SCALE = 2.5; // close enough to read a single line

export const IDENTITY: Transform = { scale: 1, x: 0, y: 0 };

export function clampScale(scale: number): number {
  if (!Number.isFinite(scale)) return MIN_SCALE;
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

/**
 * One axis of the pan clamp. Content larger than the viewport may be dragged,
 * but only until its own edge meets the viewport's — the photo can never be
 * flung off the pane leaving the reader staring at black. Content that FITS is
 * centred instead, so a stray drag cannot nudge it off-centre.
 */
function clampAxis(pos: number, content: number, viewport: number): number {
  if (content <= viewport) return (viewport - content) / 2;
  return Math.min(0, Math.max(viewport - content, pos));
}

export function clampPan(t: Transform, fit: Fit): Transform {
  return {
    scale: t.scale,
    x: clampAxis(t.x, fit.imageW * t.scale, fit.paneW),
    y: clampAxis(t.y, fit.imageH * t.scale, fit.paneH),
  };
}

/**
 * Zoom by `factor` about (fx, fy) in pane coordinates — the pinch midpoint, a
 * double-tapped note, or the pane centre for the buttons. The bit of photo
 * under that point stays under it, which is what makes a pinch feel attached to
 * the paper rather than to the pane.
 */
export function zoomAbout(
  t: Transform,
  factor: number,
  fx: number,
  fy: number,
  fit: Fit,
): Transform {
  const scale = clampScale(t.scale * factor);
  // The factor actually applied after clamping — using the requested one here
  // would drift the focal point once the zoom is pinned at a bound.
  const k = scale / t.scale;
  return clampPan({ scale, x: fx - k * (fx - t.x), y: fy - k * (fy - t.y) }, fit);
}

/** Zoom to an absolute scale about (fx, fy) — the double-tap. */
export function zoomTo(t: Transform, scale: number, fx: number, fy: number, fit: Fit): Transform {
  return zoomAbout(t, clampScale(scale) / t.scale, fx, fy, fit);
}

export function panBy(t: Transform, dx: number, dy: number, fit: Fit): Transform {
  return clampPan({ scale: t.scale, x: t.x + dx, y: t.y + dy }, fit);
}

/** The neutral view: fitted to the pane's width, scrolled to the top. */
export function fitTransform(fit: Fit): Transform {
  return clampPan(IDENTITY, fit);
}

export function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

export function midpoint(a: Point, b: Point): Point {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/**
 * Pinch factor between two samples of the finger spread. A missing or zero
 * previous distance means the gesture has only just started (or both fingers
 * landed on the same pixel), so there is no ratio yet — return 1 rather than an
 * Infinity/NaN that would fling the photo somewhere unrecoverable.
 */
export function pinchFactor(prev: number | null, next: number): number {
  if (prev === null || prev <= 0 || !Number.isFinite(next)) return 1;
  return next / prev;
}

/**
 * True when the photo is larger than its pane and a drag would actually move
 * something — drives the grab cursor, so the pane never invites a drag it will
 * ignore. The half-pixel slack keeps sub-pixel layout rounding from claiming a
 * perfectly fitted image is pannable.
 */
export function isPannable(t: Transform, fit: Fit): boolean {
  return fit.imageW * t.scale > fit.paneW + 0.5 || fit.imageH * t.scale > fit.paneH + 0.5;
}
