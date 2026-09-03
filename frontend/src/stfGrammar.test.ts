import { describe, expect, it } from "vitest";
import { NOTE_KINDS, noteTokenRegex } from "./stfGrammar";

describe("stfGrammar (finding #6 single source)", () => {
  it("matches sargam note tokens with octave dots and accidentals", () => {
    expect("S R_ M^ S' D,".match(noteTokenRegex())).toEqual(["S", "R_", "M^", "S'", "D,"]);
  });

  it("returns a fresh regex each call, so lastIndex is never shared across loops", () => {
    const a = noteTokenRegex();
    a.exec("S R G"); // advances a.lastIndex
    const b = noteTokenRegex();
    expect(b.lastIndex).toBe(0);
    expect(a).not.toBe(b);
  });

  it("treats only sargam and run as note-bearing kinds", () => {
    expect(NOTE_KINDS.has("sargam")).toBe(true);
    expect(NOTE_KINDS.has("run")).toBe(true);
    expect(NOTE_KINDS.has("lyric")).toBe(false);
    expect(NOTE_KINDS.has("section")).toBe(false);
  });
});
