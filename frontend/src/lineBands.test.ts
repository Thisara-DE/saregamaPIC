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
});
