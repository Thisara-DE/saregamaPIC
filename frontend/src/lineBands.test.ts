import { describe, expect, it } from "vitest";
import { bandForLine, type Band } from "./lineBands";

const bands: Band[] = [
  { y0: 0.0, y1: 0.1 },
  { y0: 0.3, y1: 0.4 },
  { y0: 0.6, y1: 0.7 },
  { y0: 0.85, y1: 0.95 },
];

describe("bandForLine", () => {
  it("returns null when there are no detected bands", () => {
    expect(bandForLine([], 0, 5)).toBeNull();
  });

  it("maps 1:1 when band and line counts match", () => {
    for (let i = 0; i < bands.length; i++) {
      expect(bandForLine(bands, i, bands.length)).toEqual(bands[i]);
    }
  });

  it("snaps proportionally to a real row when counts differ", () => {
    // 6 lines onto 4 bands: first line → first band, last → last, middle
    // proportional. Every result is one of the actual detected rows.
    expect(bandForLine(bands, 0, 6)).toEqual(bands[0]);
    expect(bandForLine(bands, 5, 6)).toEqual(bands[3]);
    for (let i = 0; i < 6; i++) {
      expect(bands).toContainEqual(bandForLine(bands, i, 6));
    }
  });

  it("uses the only band when a single row was detected", () => {
    expect(bandForLine([bands[1]!], 3, 9)).toEqual(bands[1]);
  });

  it("returns the first band for a lone line", () => {
    expect(bandForLine(bands, 0, 1)).toEqual(bands[0]);
  });

  it("clamps an out-of-range index instead of returning undefined", () => {
    expect(bandForLine(bands, 99, 4)).toEqual(bands[3]);
    expect(bandForLine(bands, -3, 4)).toEqual(bands[0]);
  });

  describe("skips title/header rows at the top (F6)", () => {
    // The real-world shape: the detector finds an extra ink row at the top for
    // the written title (and sometimes the Concert/Alto header), so there are
    // MORE bands than STF lines and the surplus sits above line 0.
    const title = { y0: 0.02, y1: 0.08 };
    const header = { y0: 0.12, y1: 0.16 };

    it("maps line 0 to the first WRITING row, not the title above it (bands = lines + 1)", () => {
      const withTitle: Band[] = [title, ...bands]; // 5 bands, title + 4 written lines
      // Without the hint the old proportional map sent line 0 to the title:
      expect(bandForLine(withTitle, 0, 4)).toEqual(title);
      // With topExtra = 1 it lands on the real first row and stays 1:1 after.
      expect(bandForLine(withTitle, 0, 4, 1)).toEqual(bands[0]);
      expect(bandForLine(withTitle, 1, 4, 1)).toEqual(bands[1]);
      expect(bandForLine(withTitle, 3, 4, 1)).toEqual(bands[3]);
    });

    it("skips both a title and a header row (bands = lines + 2)", () => {
      const withBoth: Band[] = [title, header, ...bands]; // 6 bands, 4 lines
      expect(bandForLine(withBoth, 0, 4, 2)).toEqual(bands[0]);
      expect(bandForLine(withBoth, 3, 4, 2)).toEqual(bands[3]);
    });

    it("never skips more than the real surplus, so an over-estimate self-corrects", () => {
      // Caller believes there is a title AND a header (topExtra = 2), but only a
      // header row was actually detected (1 surplus). The clamp skips just 1.
      const withHeader: Band[] = [header, ...bands]; // 5 bands, 4 lines
      expect(bandForLine(withHeader, 0, 4, 2)).toEqual(bands[0]);
      expect(bandForLine(withHeader, 3, 4, 2)).toEqual(bands[3]);
    });

    it("falls back to proportional over the remaining rows when counts still differ", () => {
      // 6 detected rows, 1 known title, 3 STF lines → 5 usable for 3 lines.
      const rows: Band[] = [title, ...bands, { y0: 0.97, y1: 0.99 }]; // 6 bands
      expect(bandForLine(rows, 0, 3, 1)).toEqual(rows[1]); // first written row
      expect(bandForLine(rows, 2, 3, 1)).toEqual(rows[5]); // last written row
      for (let i = 0; i < 3; i++) {
        const got = bandForLine(rows, i, 3, 1);
        expect(rows.slice(1)).toContainEqual(got); // never the skipped title
      }
    });

    it("defaults topExtra to 0, preserving the original mapping", () => {
      for (let i = 0; i < bands.length; i++) {
        expect(bandForLine(bands, i, bands.length)).toEqual(bandForLine(bands, i, bands.length, 0));
      }
    });
  });
});
