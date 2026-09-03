import { describe, expect, it } from "vitest";
import { deleteSongWarning } from "./songDelete";

describe("deleteSongWarning", () => {
  it("omits the pages clause when there is nothing to lose", () => {
    expect(deleteSongWarning("Sudu Nelum", 0)).toBe('Delete "Sudu Nelum"?');
  });

  it("falls back to 'Untitled song' for a blank title", () => {
    expect(deleteSongWarning("", 0)).toBe('Delete "Untitled song"?');
  });

  it("singularises a one-page song and warns photos are removed", () => {
    expect(deleteSongWarning("Solo", 1)).toBe(
      'Delete "Solo" and its 1 page? The original photos are removed too.',
    );
  });

  it("pluralises multiple pages", () => {
    expect(deleteSongWarning("Suite", 3)).toBe(
      'Delete "Suite" and its 3 pages? The original photos are removed too.',
    );
  });
});
