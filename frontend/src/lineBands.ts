/**
 * Map an STF line to its row on the photo (finding #11 auto-scroll).
 *
 * The backend returns the sheet's detected ink rows as normalized vertical bands
 * (`GET /scans/:id/line-bands`), top to bottom. The editor knows the STF lines,
 * also top to bottom, but the two counts need not match: recognition can split
 * or merge a row, a line can be blank, an annotation can sit off to the side.
 *
 * So rather than assume a 1:1 index, we place the line proportionally among the
 * detected rows and snap to the nearest real one. When the counts DO match this
 * is exactly the 1:1 mapping (line i → band i); when they differ, every line
 * still lands on an actual ink row instead of an even slice of blank paper. Both
 * sequences are monotonic top-to-bottom, so proportional placement is sound.
 *
 * Pure and separate from React, like photoZoom/stfEdit: the maths is the part
 * that goes subtly wrong and is worth testing on its own.
 */

export interface Band {
  y0: number;
  y1: number;
}

/**
 * The photo band for STF line `index` (of `lineCount` lines), or `null` when
 * there are no detected bands to scroll to (a blank page, or detection failed —
 * the editor then simply doesn't auto-scroll).
 */
export function bandForLine(bands: Band[], index: number, lineCount: number): Band | null {
  if (bands.length === 0) return null;
  if (bands.length === 1 || lineCount <= 1) return bands[0]!;
  const clampedIndex = Math.min(Math.max(index, 0), lineCount - 1);
  // Position the line proportionally, then snap to the nearest detected row.
  const j = Math.round((clampedIndex / (lineCount - 1)) * (bands.length - 1));
  return bands[Math.min(Math.max(j, 0), bands.length - 1)]!;
}
