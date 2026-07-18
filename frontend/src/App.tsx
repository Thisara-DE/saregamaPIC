import { useState } from "react";
import { SongPage } from "./pages/SongPage";
import { SongsPage } from "./pages/SongsPage";

// Two views, one state variable. Swap for a real router (react-router) when
// Phase 1 adds the gallery/viewer — don't grow this by hand past 3 views.
export default function App() {
  const [openSongId, setOpenSongId] = useState<string | null>(null);

  return (
    <>
      <header className="app-header">
        <h1>SaReGaMaPic</h1>
        <p className="tagline">Point. Shoot. Sa Re Ga Ma.</p>
      </header>
      <main>
        {openSongId === null ? (
          <SongsPage onOpenSong={setOpenSongId} />
        ) : (
          <SongPage songId={openSongId} onBack={() => setOpenSongId(null)} />
        )}
      </main>
    </>
  );
}
