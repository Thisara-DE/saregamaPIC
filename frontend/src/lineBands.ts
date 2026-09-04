/**
 * Map an STF line to its row on the photo (finding #11 auto-scroll).
 *
 * The backend returns the sheet's detected ink rows as normalized vertical bands
 * (`GET /scans/:id/line-bands`), top to bottom. The editor knows the STF lines,
 * also top to bottom, but the two counts need not match: recognition can split
 * or merge a row, a line can be blank, an annotation can sit off to the side.
 *
 * Crucially, not every detected ink row is an STF line. The written song title
 * and the Concert/Alto/beat header both sit ABOVE the first sargam row, and the
 * recognition contract stores them separately (`song.title`, `stf.header`) —
 * they never appear in `stf.lines`. So the surplus bands are systematically
 * top-heavy, which is the one distribution a bare proportional mapping handles
 * worst (finding F6). The caller passes `topExtra` — how many such non-line rows
 * it knows are present — so those top bands are skipped before mapping.
 *
 * After the skip: when the counts line up it is an exact 1:1 (line i → band
 * i + extra); when they still differ, the line is placed proportionally across
 * the REMAINING rows and snapped to a real one, so a line always lands on an
 * actual ink row rather than an even slice of blank paper.
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
 *
 * `topExtra` counts detected rows that precede the first STF line (a written
 * title and/or a header row). It is only a hint: we never skip more bands than
 * the actual surplus, so an over-estimate — e.g. a title the user typed that was
 * never on the paper — cannot strand the lines; it degrades to the smaller,
 * correct skip. Defaults to 0, which is the original proportional behaviour.
 * There is deliberately no symmetric guard for an UNDER-estimate: a surplus
 * band the caller didn't declare is treated as line 0's row (see F26 — the
 * caller derives the hint from transcribed text, which can be blank for a row
 * that is physically there).
 */
export function bandForLine(
  bands: Band[],
  index: number,
  lineCount: number,
  topExtra = 0,
): Band | null {
  if (bands.length === 0) return null;
  const clampedIndex = Math.min(Math.max(index, 0), Math.max(lineCount - 1, 0));

  // Skip the known non-line rows at the top — but never more than the real
  // surplus, so line 0 maps to the first WRITING row, not the title above it.
  const surplus = Math.max(bands.length - lineCount, 0);
  const extra = Math.min(Math.max(topExtra, 0), surplus);
  const usable = bands.length - extra;

  if (usable <= 1 || lineCount <= 1) return bands[extra]!;
  if (usable === lineCount) return bands[extra + clampedIndex]!; // exact 1:1 after the skip
  // Counts still differ (a split/merged row, a blank line, a stray band): place
  // the line proportionally across the remaining rows and snap to a real one.
  const j = extra + Math.round((clampedIndex / (lineCount - 1)) * (usable - 1));
  return bands[Math.min(Math.max(j, extra), bands.length - 1)]!;
}
