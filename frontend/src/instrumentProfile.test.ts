import { beforeEach, describe, expect, it } from "vitest";
import {
  ALTO_SAX,
  CANONICAL_S_PC,
  allProfiles,
  askedThisSession,
  bambooFlute,
  instrumentHeader,
  keyColumnHeading,
  keyColumnValue,
  loadProfile,
  markAskedThisSession,
  parseProfile,
  profileHint,
  profileName,
  sameProfile,
  saveProfile,
  serializeProfile,
  tonicFingering,
  viewSemitones,
} from "./instrumentProfile";
import { transposeLine, transposeSemitones } from "./stfTranspose";

// The tunings used throughout: the sax (identity) and two differently tuned
// flutes, as the Phase 3.6 exit criterion asks for.
const FLUTE_D = bambooFlute(2);
const FLUTE_G = bambooFlute(7);

const PCS = Array.from({ length: 12 }, (_, i) => i);

function mod12(n: number): number {
  return ((n % 12) + 12) % 12;
}

describe("viewSemitones — Alto Sax is the identity profile", () => {
  it("never rotates a sheet that is being kept in its own key", () => {
    for (const source of PCS) {
      expect(viewSemitones(ALTO_SAX, source, null)).toBe(0);
      // Selecting the sheet's own key explicitly is the same thing.
      expect(viewSemitones(ALTO_SAX, source, source)).toBe(0);
    }
  });

  it("reproduces the pre-profile key rotation for all 144 key pairs", () => {
    for (const source of PCS) {
      for (const target of PCS) {
        expect(viewSemitones(ALTO_SAX, source, target)).toBe(transposeSemitones(source, target));
      }
    }
  });
});

describe("viewSemitones — the user's worked example (2026-09-08)", () => {
  // A sheet written Concert G / Alto E, played on a D flute, keeping concert G.
  const CONCERT_G = 7;

  it("re-fingers a concert-G sheet down 4 semitones for a D flute", () => {
    expect(viewSemitones(FLUTE_D, CONCERT_G, null)).toBe(-4);
  });

  it("puts the tonic on M — the sax fingers the same tune from D", () => {
    expect(tonicFingering(FLUTE_D, CONCERT_G)).toBe("M");
    expect(tonicFingering(ALTO_SAX, CONCERT_G)).toBe("D");
  });

  it("rewrites the letters while the sounding pitches stay put", () => {
    const stored = "S R - G | P D N S'";
    expect(transposeLine(stored, viewSemitones(FLUTE_D, CONCERT_G, null))).toBe(
      "D,_ N,_ - S | G_ M P D_",
    );
  });

  it("still transposes on top of the re-fingering when a new key is chosen", () => {
    // Concert G sheet, D flute, now asked for concert C: a further -7 (folded
    // to +5) on top of the -4 anchor shift.
    expect(viewSemitones(FLUTE_D, CONCERT_G, 0)).toBe(1);
    expect(viewSemitones(ALTO_SAX, CONCERT_G, 0)).toBe(5);
  });
});

describe("viewSemitones — the invariant that defines the feature", () => {
  // Every stored note is a fingering; on the canonical (alto) anchor it sounds
  // CANONICAL_S_PC + offset. After viewing through ANY profile at ANY target
  // key, the note must sound exactly (target - source) semitones from that —
  // i.e. the instrument changes the fingering and NEVER the music, while the
  // key selector changes the music and nothing else. This is the whole of
  // "keep the concert key", asserted over every combination.
  it("preserves sounding pitch across all 12 tunings x 12 source x 12 target keys", () => {
    for (const sPc of PCS) {
      const profile = bambooFlute(sPc);
      for (const source of PCS) {
        for (const target of PCS) {
          const k = viewSemitones(profile, source, target);
          for (const offset of PCS) {
            const soundsAsStored = mod12(CANONICAL_S_PC + offset);
            const soundsNow = mod12(profile.sPc + offset + k);
            expect(soundsNow).toBe(mod12(soundsAsStored + (target - source)));
          }
        }
      }
    }
  });

  it("always picks the nearest octave, so no view inflates octave dots", () => {
    for (const sPc of PCS) {
      for (const source of [...PCS, null]) {
        for (const target of [...PCS, null]) {
          const k = viewSemitones(bambooFlute(sPc), source, target);
          expect(k).toBeGreaterThanOrEqual(-5);
          expect(k).toBeLessThanOrEqual(6);
        }
      }
    }
  });

  it("is exactly reversible — a flute view rotated back is the stored text", () => {
    const stored = "S R'_ - G, | P M^ N S'";
    for (const sPc of PCS) {
      const k = viewSemitones(bambooFlute(sPc), 7, null);
      expect(transposeLine(transposeLine(stored, k), -k)).toBe(stored);
    }
  });

  it("still re-fingers when the header scale is unknown — only the key half is lost", () => {
    // Finding F35. An unparseable header costs the KEY shift, which needs a
    // tonic; the ANCHOR shift never mentions the key, and dropping it would hand
    // a flute player alto-sax fingerings under a picker reading "flute in D".
    // The headline invariant above must therefore hold here too, so this case is
    // asserted against it rather than against a hard-coded number.
    for (const sPc of PCS) {
      const profile = bambooFlute(sPc);
      const k = viewSemitones(profile, null, null);
      for (const offset of PCS) {
        expect(mod12(profile.sPc + offset + k)).toBe(mod12(CANONICAL_S_PC + offset));
      }
      // No source key means no interval, so asking for a target changes nothing.
      expect(viewSemitones(profile, null, 3)).toBe(k);
    }
    // The sax is still the identity: its anchor IS the canonical one.
    expect(viewSemitones(ALTO_SAX, null, null)).toBe(0);
  });
});

describe("header and selector labels", () => {
  it("keeps the standard Concert/Alto pair for the sax", () => {
    expect(instrumentHeader(ALTO_SAX, 7)).toBe("Alto E"); // concert G -> alto E
    expect(keyColumnValue(ALTO_SAX, 7)).toBe("E");
    expect(keyColumnHeading(ALTO_SAX)).toBe("Alto");
    expect(profileHint(ALTO_SAX)).toMatch(/major 6th/);
  });

  it("names the tuning and the tonic fingering for a flute", () => {
    expect(instrumentHeader(FLUTE_D, 7)).toBe("Flute D · tonic M");
    expect(instrumentHeader(FLUTE_G, 7)).toBe("Flute G · tonic S");
    expect(keyColumnValue(FLUTE_D, 7)).toBe("M");
    expect(keyColumnHeading(FLUTE_D)).toBe("Tonic");
    expect(profileHint(FLUTE_D)).toBe("Fingerings for a flute in D — S sounds concert D");
  });

  it("names a flute, but not the sax, when the header scale is unknown", () => {
    // Each half keeps what it can still know. The flute's letters HAVE been
    // re-fingered for it, so its tuning has to be on screen; it just has no
    // tonic to point at. The sax re-fingers nothing and its label is only ever
    // a key, so with no key it says nothing.
    expect(instrumentHeader(ALTO_SAX, null)).toBe("");
    expect(instrumentHeader(FLUTE_D, null)).toBe("Flute D");
  });

  it("spells accidental fingerings with ♭/♯, never STF's _ and ^", () => {
    expect(tonicFingering(FLUTE_D, 3)).toBe("R♭"); // concert E♭ on a D flute
    expect(tonicFingering(FLUTE_D, 8)).toBe("M♯"); // concert A♭ on a D flute
  });

  it("names profiles for menus", () => {
    expect(profileName(ALTO_SAX)).toBe("Alto Sax");
    expect(profileName(FLUTE_D)).toBe("Bamboo flute in D");
    expect(profileName(bambooFlute(3))).toBe("Bamboo flute in E♭");
  });

  it("offers the sax plus all twelve flute tunings, the sax first", () => {
    const all = allProfiles();
    expect(all).toHaveLength(13);
    expect(all[0]).toEqual(ALTO_SAX);
    expect(all.slice(1).map((p) => p.sPc)).toEqual(PCS);
    expect(all.slice(1).every((p) => p.kind === "bamboo-flute")).toBe(true);
  });
});

describe("persistence", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it("round-trips every profile through storage", () => {
    for (const profile of allProfiles()) {
      saveProfile(profile);
      expect(sameProfile(loadProfile(), profile)).toBe(true);
      expect(parseProfile(serializeProfile(profile))).toEqual(profile);
    }
  });

  it("defaults to the Alto Sax rather than trusting a bad stored value", () => {
    // An older build's value, a hand-edited entry, an out-of-range pitch class:
    // a stored preference must never be able to break the viewer.
    for (const junk of [null, "", "flute", "bamboo-flute:", "bamboo-flute:12", "bamboo-flute:-1"]) {
      expect(parseProfile(junk)).toEqual(ALTO_SAX);
    }
    expect(loadProfile()).toEqual(ALTO_SAX); // nothing stored at all
  });

  it("remembers the instrument across sessions but asks once per session", () => {
    saveProfile(FLUTE_G);
    expect(askedThisSession()).toBe(false);
    markAskedThisSession();
    expect(askedThisSession()).toBe(true);

    // A new playing session (the tab/app closed) clears the ask but keeps the
    // instrument — that is the whole point of the two storage lifetimes.
    sessionStorage.clear();
    expect(askedThisSession()).toBe(false);
    expect(sameProfile(loadProfile(), FLUTE_G)).toBe(true);
  });
});
