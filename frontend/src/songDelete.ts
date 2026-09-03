/**
 * The confirm() text for deleting a song, single-sourced so the gallery
 * (SongsPage) and the song detail (SongPage) can never drift apart.
 *
 * Takes the raw title so the "Untitled song" fallback for a blank title lives
 * here too. `pages` is the number of stored scans; the 0-page wording drops the
 * "and its N pages / photos removed" clause since there is nothing to lose.
 */
export function deleteSongWarning(title: string, pages: number): string {
  const displayTitle = title || "Untitled song";
  if (pages === 0) return `Delete "${displayTitle}"?`;
  return (
    `Delete "${displayTitle}" and its ${pages} ${pages === 1 ? "page" : "pages"}? ` +
    "The original photos are removed too."
  );
}
