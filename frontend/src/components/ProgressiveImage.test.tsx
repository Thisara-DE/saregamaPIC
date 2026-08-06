import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProgressiveImage } from "./ProgressiveImage";

describe("ProgressiveImage (#15 preview-first paint)", () => {
  it("shows the preview until the full image loads, then swaps to it", () => {
    render(<ProgressiveImage preview="/preview.jpg" full="/full.jpg" alt="Page 1" />);

    // Two <img>s exist (the full one is fetching while hidden), but only the
    // preview is displayed at first.
    const imgs = screen.getAllByRole("img", { hidden: true }) as HTMLImageElement[];
    const full = imgs.find((i) => i.getAttribute("src") === "/full.jpg")!;
    const preview = imgs.find((i) => i.getAttribute("src") === "/preview.jpg")!;
    expect(full.style.display).toBe("none");
    expect(preview).toBeTruthy();

    // Full image finishes loading → preview is dropped, full is shown.
    fireEvent.load(full);
    expect(full.style.display).toBe("");
    expect(screen.queryByRole("img", { name: "Page 1" })).toBe(full);
    expect(document.querySelector('img[src="/preview.jpg"]')).toBeNull();
  });
});
