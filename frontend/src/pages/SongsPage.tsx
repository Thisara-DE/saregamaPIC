import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { importSong, listSongs, scanThumbnailUrl } from "../api/client";
import type { Song } from "../api/types";

export function SongsPage() {
  const navigate = useNavigate();
  const [songs, setSongs] = useState<Song[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const cameraInput = useRef<HTMLInputElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    listSongs()
      .then(setSongs)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (!selectedFile) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(selectedFile);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [selectedFile]);

  function selectFile(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    setSelectedFile(file);
    setError(null);
  }

  function cancelSelection() {
    setSelectedFile(null);
    setNewTitle("");
    if (cameraInput.current) cameraInput.current.value = "";
    if (fileInput.current) fileInput.current.value = "";
  }

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedFile || creating) return;
    setCreating(true);
    setError(null);
    try {
      const created = await importSong(selectedFile, newTitle.trim());
      navigate(`/songs/${created.song.id}/pages/${created.scan.page_no}/edit`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setCreating(false);
    }
  }

  return (
    <section>
      <div className="new-song">
        <h2>Upload a new song</h2>
        <p className="muted">
          Start with the sheet. You can name it now, or recognition can copy a title
          written at the top.
        </p>
        <input
          ref={cameraInput}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={(event) => selectFile(event.target.files)}
        />
        <input
          ref={fileInput}
          type="file"
          accept="image/*"
          hidden
          onChange={(event) => selectFile(event.target.files)}
        />
        {!selectedFile ? (
          <div className="capture-actions">
            <button className="primary" onClick={() => cameraInput.current?.click()}>
              📷 Take a picture
            </button>
            <button onClick={() => fileInput.current?.click()}>Choose image…</button>
          </div>
        ) : (
          <form className="new-song-details" onSubmit={handleCreate}>
            {previewUrl && <img src={previewUrl} alt="Selected sheet preview" />}
            <div>
              <label htmlFor="new-song-title">Song name <span className="muted">(optional)</span></label>
              <input
                id="new-song-title"
                type="text"
                value={newTitle}
                maxLength={200}
                placeholder="Leave blank to read it from the sheet"
                onChange={(event) => setNewTitle(event.target.value)}
              />
              <div className="capture-actions">
                <button className="primary" type="submit" disabled={creating}>
                  {creating ? "Adding…" : "Add song"}
                </button>
                <button type="button" disabled={creating} onClick={cancelSelection}>
                  Choose another
                </button>
              </div>
            </div>
          </form>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {songs === null && !error && <p className="muted">Loading…</p>}
      {songs !== null && songs.length === 0 && (
        <p className="muted">No songs yet — photograph or choose your first sheet above.</p>
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
              <span className="song-title">{song.title || "Untitled song"}</span>
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
