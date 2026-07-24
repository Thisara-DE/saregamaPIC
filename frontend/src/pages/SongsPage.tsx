import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  deleteSong,
  importSong,
  listSongs,
  renameSong,
  scanThumbnailUrl,
} from "../api/client";
import type { Song } from "../api/types";

export function SongsPage() {
  const navigate = useNavigate();
  const [songs, setSongs] = useState<Song[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
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

  // An open menu should not survive a tap elsewhere or an Escape.
  useEffect(() => {
    if (menuFor === null) return;
    function dismiss(event: Event) {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setMenuFor(null);
        return;
      }
      // A pointerdown INSIDE the open menu (its ⋯ button or an item) must not
      // close it here: that fires before the item's click, so tearing the menu
      // down on pointerdown unmounts the button and the click never lands — the
      // items would silently do nothing. Let those handlers run; close only on
      // a tap that lands outside.
      if (event.target instanceof Element && event.target.closest(".song-menu-wrap")) return;
      setMenuFor(null);
    }
    document.addEventListener("pointerdown", dismiss);
    document.addEventListener("keydown", dismiss);
    return () => {
      document.removeEventListener("pointerdown", dismiss);
      document.removeEventListener("keydown", dismiss);
    };
  }, [menuFor]);

  function startRename(song: Song) {
    setMenuFor(null);
    setRenamingId(song.id);
    setRenameValue(song.title);
    setError(null);
  }

  function cancelRename() {
    setRenamingId(null);
    setRenameValue("");
  }

  async function submitRename(song: Song) {
    const title = renameValue.trim();
    if (!title) return;
    try {
      const updated = await renameSong(song.id, title);
      setSongs((current) =>
        (current ?? []).map((s) => (s.id === song.id ? { ...s, title: updated.title } : s)),
      );
      cancelRename();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleDelete(song: Song) {
    setMenuFor(null);
    const displayTitle = song.title || "Untitled song";
    const pages = song.scan_count;
    const warning =
      pages === 0
        ? `Delete "${displayTitle}"?`
        : `Delete "${displayTitle}" and its ${pages} ${pages === 1 ? "page" : "pages"}? ` +
          "The original photos are removed too.";
    if (!window.confirm(warning)) return;
    try {
      await deleteSong(song.id);
      setSongs((current) => (current ?? []).filter((s) => s.id !== song.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

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
          <li key={song.id} className="song-card">
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
              {renamingId === song.id ? (
                // Rendered outside the Link below — this keeps the row's layout
                // stable while the inline form takes the title's place.
                <span className="song-title" />
              ) : (
                <span className="song-title">{song.title || "Untitled song"}</span>
              )}
              <span className="muted">
                {song.scan_count} {song.scan_count === 1 ? "page" : "pages"}
              </span>
            </Link>

            {renamingId === song.id && (
              <form
                className="song-rename"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitRename(song);
                }}
              >
                <label className="sr-only" htmlFor={`rename-${song.id}`}>
                  Song name
                </label>
                <input
                  id={`rename-${song.id}`}
                  type="text"
                  autoFocus
                  maxLength={200}
                  value={renameValue}
                  placeholder="Song name"
                  onChange={(event) => setRenameValue(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") cancelRename();
                  }}
                />
                <button className="primary" type="submit" disabled={!renameValue.trim()}>
                  Save
                </button>
                <button type="button" onClick={cancelRename}>
                  Cancel
                </button>
              </form>
            )}

            <div className="song-menu-wrap">
              <button
                type="button"
                className="song-menu-button"
                aria-label={`Actions for ${song.title || "Untitled song"}`}
                aria-haspopup="menu"
                aria-expanded={menuFor === song.id}
                onClick={() => setMenuFor(menuFor === song.id ? null : song.id)}
              >
                ⋯
              </button>

              {menuFor === song.id && (
                <div className="song-menu" role="menu">
                  <button type="button" role="menuitem" onClick={() => startRename(song)}>
                    Rename
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    // Greyed out until something has actually been transcribed.
                    disabled={song.digital_page_no === null}
                    title={
                      song.digital_page_no === null
                        ? "No digital version yet — transcribe a page first"
                        : undefined
                    }
                    onClick={() => {
                      setMenuFor(null);
                      navigate(`/songs/${song.id}/pages/${song.digital_page_no}`);
                    }}
                  >
                    Open digital version
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={song.scan_count === 0}
                    title={song.scan_count === 0 ? "Add a page first" : undefined}
                    onClick={() => {
                      setMenuFor(null);
                      navigate(
                        `/songs/${song.id}/pages/${song.digital_page_no ?? 1}/edit`,
                      );
                    }}
                  >
                    Edit digital version
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className="danger-item"
                    onClick={() => void handleDelete(song)}
                  >
                    Delete song
                  </button>
                </div>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
