import { Navigate, Outlet, Route, Routes } from "react-router-dom";
import { EditorPage } from "./pages/EditorPage";
import { PageViewer } from "./pages/PageViewer";
import { SongPage } from "./pages/SongPage";
import { SongsPage } from "./pages/SongsPage";

// Routing arrived with Phase 1's third view (the page viewer). The viewer
// renders outside the Shell so the
// photo gets the whole screen.
function Shell() {
  return (
    <>
      <header className="app-header">
        <h1>SaReGaMaPic</h1>
        <p className="tagline">Point. Shoot. Sa Re Ga Ma.</p>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route path="/" element={<SongsPage />} />
        <Route path="/songs/:songId" element={<SongPage />} />
      </Route>
      <Route path="/songs/:songId/pages/:pageNo" element={<PageViewer />} />
      <Route path="/songs/:songId/pages/:pageNo/edit" element={<EditorPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
