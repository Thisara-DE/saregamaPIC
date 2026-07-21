import { describe, expect, it } from "vitest";
import {
  pitchClassName,
  scalePitchClass,
  transposeLine,
  transposeLineOfKind,
} from "./stfTranspose";

describe("scalePitchClass", () => {
  it("parses plain, sharp, flat, and quality-suffixed scale names", () => {
    expect(scalePitchClass("C")).toBe(0);
    expect(scalePitchClass("D")).toBe(2);
    expect(scalePitchClass("B")).toBe(11);
    expect(scalePitchClass("Eb")).toBe(3);
    expect(scalePitchClass("E♭")).toBe(3);
    expect(scalePitchClass("F#")).toBe(6);
    expect(scalePitchClass("D maj")).toBe(2);
    expect(scalePitchClass("C minor")).toBe(0);
  });

  it("returns null for a non-note leading token", () => {
    expect(scalePitchClass("")).toBeNull();
    expect(scalePitchClass("H")).toBeNull();
  });

  it("agrees with the Tharuda header's concert/alto +9 relationship", () => {
    const concert = scalePitchClass("D");
    const alto = scalePitchClass("B");
    expect(concert).not.toBeNull();
    expect(((concert! + 9) % 12)).toBe(alto);
  });
});

describe("pitchClassName", () => {
  it("names each pitch class and wraps", () => {
    expect(pitchClassName(0)).toBe("C");
    expect(pitchClassName(2)).toBe("D");
    expect(pitchClassName(11)).toBe("B");
    expect(pitchClassName(12)).toBe("C");
    expect(pitchClassName(-1)).toBe("B");
  });
});

describe("transposeLine — canonical rotation", () => {
  it("is the identity for a full-octave / zero shift (byte-for-byte)", () => {
    const line = "G - (G_G) | R' M^ D, |";
    expect(transposeLine(line, 0)).toBe(line);
    expect(transposeLine(line, 12)).toBe("G' - (G'_G') | R'' M'^ D |");
  });

  it("rotates each pitch class to its single canonical spelling (+1 semitone)", () => {
    // S R_ R G_ G M M^ P D_ D N_ N  →  each up one semitone.
    expect(transposeLine("S R_ R G_ G M M^ P D_ D N_ N", 1)).toBe(
      "R_ R G_ G M M^ P D_ D N_ N S'",
    );
  });

  it("carries a note across the S boundary into the next octave up", () => {
    // N (11) + 1 = 12 → S one octave up; M^ (6) stays mid-octave.
    expect(transposeLine("N", 1)).toBe("S'");
    // N(11)+2 → R♭ one octave up; M♯(6)+2 → D♭.
    expect(transposeLine("N M^", 2)).toBe("R'_ D_");
  });

  it("carries a note across the S boundary into the octave below", () => {
    // S (0) − 1 → N of the octave below.
    expect(transposeLine("S", -1)).toBe("N,");
    expect(transposeLine("R", -3)).toBe("N,");
  });

  it("hand spot-check: Tharuda line 2 transposed +9 (concert D → alto B)", () => {
    const src = "G - (GG) (G_G) | - R_ N_ D | G - (GG) (GG_) | R - - - |";
    const want = "R'_ - (R'_R'_) (S'R'_) | - N_ P' M'^ | R'_ - (R'_R'_) (R'_S') | N - - - |";
    expect(transposeLine(src, 9)).toBe(want);
  });
});

describe("transposeLine — verbatim preservation (flag, don't fix)", () => {
  it("keeps holds, rests, barlines, repeats, curves, spacing exactly; only notes move", () => {
    // Non-pitch tokens and every space are untouched; the notes shift +2.
    expect(transposeLine("S - (S R) + | // ", 2)).toBe("R - (R G) + | // ");
    // Double spaces are preserved byte-for-byte.
    expect(transposeLine("S  -  R", 2)).toBe("R  -  G");
  });

  it("transposes notes INSIDE brackets (a real part in the same key), keeping []", () => {
    // [ … ] delimiters pass through; the pitches within are still rotated.
    expect(transposeLine("[D N_]", 2)).toBe("[N S']");
  });

  it("leaves an alien letter (misread B) untouched", () => {
    expect(transposeLine("B_ R G", 3)).toBe("B_ M P");
  });

  it("leaves an illegal accidental untouched (S/P accidental, M flat, R^)", () => {
    expect(transposeLine("S_", 5)).toBe("S_");
    expect(transposeLine("P^", 5)).toBe("P^");
    expect(transposeLine("M_", 5)).toBe("M_");
    expect(transposeLine("R^", 5)).toBe("R^");
    // both marks at once → illegal → verbatim
    expect(transposeLine("R_^", 5)).toBe("R_^");
  });
});

describe("transposeLineOfKind", () => {
  it("only rotates sargam/run lines; free text passes through", () => {
    expect(transposeLineOfKind("sargam", "S", 2)).toBe("R");
    expect(transposeLineOfKind("run", "S", 2)).toBe("R");
    expect(transposeLineOfKind("lyric", "S R G", 2)).toBe("S R G");
    expect(transposeLineOfKind("section", "Intro", 2)).toBe("Intro");
  });
});

// --- Exhaustive round-trip: transposition must be losslessly reversible ---

// The 12 canonical note tokens (what renderAbsolute emits), across five octaves.
const CANON = ["S", "R_", "R", "G_", "G", "M", "M^", "P", "D_", "D", "N_", "N"];

describe("round-trip reversibility (the core guarantee)", () => {
  it("transpose(+k) then transpose(−k) restores every canonical note, all octaves", () => {
    const octaveMarks = [",,", ",", "", "'", "''"];
    for (const dots of octaveMarks) {
      for (const base of CANON) {
        // place octave dots after the letter, before any accidental (canonical order)
        const token = base[0] + dots + base.slice(1);
        for (let k = 0; k < 12; k++) {
          const there = transposeLine(token, k);
          const back = transposeLine(there, -k);
          expect(back).toBe(token);
        }
      }
    }
  });
});

// --- The reviewed Tharuda sheet: round-trip must return the EXACT original ---

const THARUDA_SARGAM_LINES = [
  "G - (GG) (G_G) | - R_ N_ D | G - (GG) (GG_) | R - - - |",
  "M^ - (M^M^) (MM^) | - R G M^ | D_ - (D_D_) M^ | G - - - |",
  "R G D - |(DD) D_ D - | (N_D) D_ - D | N_ (R'_N_) D D_ |",
  "G  G  (GG) - | M^ M^ (M^M^) - | D_ D_ (D_D_) | D - - - |",
  "+ (R_G) (M^D) (M^G) | R' (R'R') R_ - [D N_ D R_ -] | (N_R'_) N' (D'N'_) D' | D_ G M^ - [G - M^ - D_]|",
  "+ D_ (D_G) (M^G) | (GM^) (M^N_) (N_N) N_ | (R'N_) (R'_D) (N_D_) (N_N_) | D - - - |",
  "M^ (M^D) (M^G) (GM^) | (M^N_) N_ (N_R'_) (N_D) | (DN_) (R'_G') G' (G'M'^) | (R'_N_) (D'N_) R_ - |",
  "R' (R'R'_) R (R'G') | (R'_R') (R'_N_) (R'_N_) N_ | D_ (D_G) (M^G) (GM^) | N_ D (DD) - |",
];

describe("Tharuda reviewed sheet", () => {
  it("round-trips to the exact original STF for every interval", () => {
    for (const line of THARUDA_SARGAM_LINES) {
      for (let k = 1; k < 12; k++) {
        expect(transposeLine(transposeLine(line, k), -k)).toBe(line);
      }
    }
  });

  it("transpose(line, 0) is byte-for-byte identity on real stored tokens", () => {
    for (const line of THARUDA_SARGAM_LINES) {
      expect(transposeLine(line, 0)).toBe(line);
    }
  });
});
