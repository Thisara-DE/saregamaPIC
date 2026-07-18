import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { createSong, listSongs, scanThumbnailUrl } from "../api/client";
import type { Song } from "../api/types";

export function SongsPage() {
  const [songs, setSongs] = useState<Song[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    listSongs()
      .then(setSongs)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    const title = newTitle.trim();
    if (!title || creating) return;
    setCreating(true);
    setError(null);
    try {
      const song = await createSong(title);
      setSongs((prev) => [song, ...(prev ?? [])]);
      setNewTitle("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

  return (
    <section>
      <form className="new-song" onSubmit={handleCreate}>
        <input
          type="text"
          value={newTitle}
          placeholder="New song title…"
          aria-label="New song title"
          onChange={(e) => setNewTitle(e.target.value)}
        />
        <button type="submit" disabled={!newTitle.trim() || creating}>
          Add
        </button>
      </form>

      {error && <p className="error">{error}</p>}
      {songs === null && !error && <p className="muted">Loading…</p>}
      {songs !== null && songs.length === 0 && (
        <p className="muted">No songs yet — add one above, then photograph its sheet.</p>
      )}

      <ul className="song-list">
        {songs?.map((song) => (
          <li key={song.id}>
            <Link className="song-row" to={`/songs/${song.id}`}>
              {song.cover_scan_id ? (
                <img
                  className="song-cover"
                  src={scanThumbnailUrl(song.cover_scan_id)}
                  alt=""
                  loading="lazy"
                />
              ) : (
                <span className="song-cover placeholder" aria-hidden="true">
                  ♪
                </span>
              )}
              <span className="song-title">{song.title}</span>
              <span className="muted">
                {song.scan_count} {song.scan_count === 1 ? "page" : "pages"}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
