import { describe, expect, it } from "vitest";
import { insertToken, noteTokenAt, toggleMark } from "./stfEdit";

describe("noteTokenAt", () => {
  it("finds the note the caret is inside or just after", () => {
    expect(noteTokenAt("S R G", 1)).toEqual([0, 1]); // caret right after S
    expect(noteTokenAt("S R G", 3)).toEqual([2, 3]); // caret on R
  });

  it("falls back to the nearest note left of the caret", () => {
    expect(noteTokenAt("S | ", 2)).toEqual([0, 1]); // caret in the barline gap → S
  });

  it("returns null when no note precedes the caret", () => {
    expect(noteTokenAt("  | S", 1)).toBeNull();
  });
});

describe("toggleMark", () => {
  it("adds a flat to the note just typed", () => {
    expect(toggleMark("S G", 3, "_")).toEqual({ text: "S G_", caret: 4 });
  });

  it("removes a mark that is already present (toggle off)", () => {
    expect(toggleMark("S G_", 4, "_")).toEqual({ text: "S G", caret: 3 });
  });

  it("toggles sharp and octave marks independently", () => {
    expect(toggleMark("M", 1, "^")).toEqual({ text: "M^", caret: 2 });
    expect(toggleMark("S'", 2, "'")).toEqual({ text: "S", caret: 1 });
    expect(toggleMark("P", 1, ",")).toEqual({ text: "P,", caret: 2 });
  });

  it("no-ops when the caret is not on a note", () => {
    expect(toggleMark("  |", 1, "_")).toEqual({ text: "  |", caret: 1 });
  });
});

describe("insertToken", () => {
  it("inserts with single spaces and no pile-up", () => {
    expect(insertToken("S R", 3, "|")).toEqual({ text: "S R | ", caret: 6 });
    expect(insertToken("S R ", 4, "|")).toEqual({ text: "S R | ", caret: 6 });
  });
});
