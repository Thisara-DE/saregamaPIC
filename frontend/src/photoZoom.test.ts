import { describe, expect, it } from "vitest";
import {
  bandIntoView,
  clampPan,
  clampScale,
  distance,
  fitTransform,
  IDENTITY,
  isPannable,
  MAX_SCALE,
  midpoint,
  panBy,
  pinchFactor,
  zoomAbout,
  zoomTo,
  type Fit,
  type Transform,
} from "./photoZoom";

// A phone: a 38vh pane with a portrait sheet fitted to its width, so the photo
// is taller than the pane and there is somewhere to pan even at scale 1.
const phone: Fit = { paneW: 360, paneH: 280, imageW: 360, imageH: 480 };
// A desktop half-split: the whole sheet fits, so nothing should ever move.
const desktop: Fit = { paneW: 500, paneH: 700, imageW: 500, imageH: 667 };

describe("clampScale", () => {
  it("holds the scale inside its bounds and survives a NaN", () => {
    expect(clampScale(0.2)).toBe(1);
    expect(clampScale(3)).toBe(3);
    expect(clampScale(99)).toBe(MAX_SCALE);
    // A pinch whose previous distance was 0 used to produce NaN here; falling
    // back to 1 keeps the photo on screen instead of vanishing it.
    expect(clampScale(Number.NaN)).toBe(1);
  });
});

describe("clampPan", () => {
  it("centres content that fits, so a stray drag cannot nudge it off-centre", () => {
    expect(clampPan({ scale: 1, x: -80, y: -80 }, desktop)).toEqual({
      scale: 1,
      x: 0, // width matches the pane exactly
      y: 16.5, // (700 - 667) / 2
    });
  });

  it("stops a drag at the image's own edge, never leaving a black gap", () => {
    // The sheet is 480 tall in a 280 pane, so it may rise by at most 200px.
    expect(clampPan({ scale: 1, x: 0, y: -500 }, phone).y).toBe(-200);
    expect(clampPan({ scale: 1, x: 0, y: 60 }, phone).y).toBe(0);
  });
});

describe("panBy", () => {
  it("pans vertically at scale 1 but not horizontally when the width already fits", () => {
    const dragged = panBy(IDENTITY, -40, -50, phone);
    expect(dragged.y).toBe(-50);
    expect(dragged.x).toBe(0);
  });

  it("pans both ways once zoomed in", () => {
    const zoomed = { scale: 2, x: -100, y: -100 };
    expect(panBy(zoomed, -30, -30, phone)).toEqual({ scale: 2, x: -130, y: -130 });
  });
});

describe("zoomAbout", () => {
  it("keeps the bit of photo under the focal point under it", () => {
    const focal = { x: 180, y: 140 };
    // Where the focal point sits in the image's own coordinates, before/after.
    const imagePoint = (t: { scale: number; x: number; y: number }) => ({
      x: (focal.x - t.x) / t.scale,
      y: (focal.y - t.y) / t.scale,
    });
    const next = zoomAbout(IDENTITY, 2, focal.x, focal.y, phone);
    expect(next.scale).toBe(2);
    expect(imagePoint(next)).toEqual(imagePoint(IDENTITY));
  });

  it("does not drift the focal point when the zoom is pinned at the maximum", () => {
    // Asking for 4x from 4x clamps to 6x. Re-using the REQUESTED factor here
    // would slide the photo under the fingers; only the applied one holds.
    const start = { scale: 4, x: 0, y: 0 };
    const next = zoomAbout(start, 4, 100, 100, phone);
    expect(next.scale).toBe(MAX_SCALE);
    expect((100 - next.x) / next.scale).toBeCloseTo((100 - start.x) / start.scale, 10);
  });

  it("re-clamps the pan so zooming back out never strands the photo off the pane", () => {
    // Zoom hard into the bottom-right corner, then all the way back out. The
    // pan that was legal at 4x is far outside the legal range at 1x, so without
    // the re-clamp the reader would be left looking at black.
    const zoomedIn = zoomAbout(IDENTITY, 4, 360, 280, phone);
    expect(zoomedIn).toEqual({ scale: 4, x: -1080, y: -840 });
    expect(zoomAbout(zoomedIn, 0.1, 360, 280, phone)).toEqual({ scale: 1, x: 0, y: 0 });
  });
});

describe("zoomTo", () => {
  it("reaches an absolute scale about the tapped point (the double-tap)", () => {
    const next = zoomTo(IDENTITY, 2.5, 180, 140, phone);
    expect(next.scale).toBe(2.5);
    expect((180 - next.x) / next.scale).toBeCloseTo(180, 10);
  });
});

describe("fitTransform", () => {
  it("returns the whole width at the top of the sheet", () => {
    expect(fitTransform(phone)).toEqual({ scale: 1, x: 0, y: 0 });
  });

  it("centres a sheet that fits its pane outright", () => {
    expect(fitTransform(desktop)).toEqual({ scale: 1, x: 0, y: 16.5 });
  });
});

describe("pinchFactor", () => {
  it("returns the ratio of the finger spread", () => {
    expect(pinchFactor(100, 150)).toBe(1.5);
    expect(pinchFactor(150, 75)).toBe(0.5);
  });

  it("returns 1 rather than Infinity/NaN when there is no usable previous sample", () => {
    expect(pinchFactor(null, 120)).toBe(1); // gesture just started
    expect(pinchFactor(0, 120)).toBe(1); // both fingers on the same pixel
    expect(pinchFactor(100, Number.NaN)).toBe(1);
  });
});

describe("isPannable", () => {
  it("is true only when a drag would actually move something", () => {
    expect(isPannable(IDENTITY, phone)).toBe(true); // taller than the pane
    expect(isPannable(IDENTITY, desktop)).toBe(false); // fits outright
    expect(isPannable({ scale: 2, x: 0, y: 0 }, desktop)).toBe(true);
  });
});

describe("pointer geometry", () => {
  it("measures the spread and midpoint of two fingers", () => {
    expect(distance({ x: 0, y: 0 }, { x: 3, y: 4 })).toBe(5);
    expect(midpoint({ x: 0, y: 10 }, { x: 20, y: 30 })).toEqual({ x: 10, y: 20 });
  });
});

describe("bandIntoView (per-line auto-scroll)", () => {
  // phone: image 480 tall in a 280 pane, so at scale 1 the pane shows image
  // rows 0..280 and a lower band is off-screen.
  it("leaves a band that is already fully visible exactly where it is", () => {
    // image rows 48..96 at IDENTITY — well inside the visible 0..280
    expect(bandIntoView(IDENTITY, 0.1, 0.2, phone)).toBe(IDENTITY);
  });

  it("scrolls a band off the bottom into view, clamped flush to the edge", () => {
    // last row (image 432..480) → bottom-locked, no black below it
    const t = bandIntoView(IDENTITY, 0.9, 1.0, phone);
    expect(t).toEqual({ scale: 1, x: 0, y: -200 });
    // the band now sits inside the pane
    const top = t.y + 0.9 * phone.imageH * t.scale;
    const bottom = t.y + 1.0 * phone.imageH * t.scale;
    expect(top).toBeGreaterThanOrEqual(0);
    expect(bottom).toBeLessThanOrEqual(phone.paneH);
  });

  it("scrolls back up to a band off the top", () => {
    const bottomLocked: Transform = { scale: 1, x: 0, y: -200 };
    expect(bandIntoView(bottomLocked, 0.0, 0.05, phone).y).toBe(0);
  });

  it("keeps the current zoom, only moving vertically", () => {
    const zoomed: Transform = { scale: 2, x: -50, y: -100 };
    const t = bandIntoView(zoomed, 0.9, 1.0, phone);
    expect(t.scale).toBe(2);
    expect(t.x).toBe(-50); // horizontal position untouched
  });
});
