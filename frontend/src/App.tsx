import { useEffect, useState } from "react";
import {
  createRoutesFromElements,
  Navigate,
  Outlet,
  Route,
  useLocation,
  useOutletContext,
} from "react-router-dom";
import { ApiError, getCurrentUser, logout } from "./api/client";
import type { AuthUser } from "./api/types";
import { EditorPage } from "./pages/EditorPage";
import { PageViewer } from "./pages/PageViewer";
import { SongPage } from "./pages/SongPage";
import { SongsPage } from "./pages/SongsPage";

// The signed-in user + a sign-out callback, handed down from the auth gate to
// the Shell (and anything else that needs them) via the router's outlet context.
type AppContext = { user: AuthUser; onSignedOut: () => void };

// Routing arrived with Phase 1's third view (the page viewer). The viewer
// renders outside the Shell so the photo gets the whole screen.
function Shell() {
  const { user, onSignedOut } = useOutletContext<AppContext>();

  async function signOut() {
    await logout();
    onSignedOut();
  }

  return (
    <>
      <header className="app-header">
        <div>
          <h1>SaReGaMaPic</h1>
          <p className="tagline">Point. Shoot. Sa Re Ga Ma.</p>
        </div>
        <div className="account-menu">
          <span>{user.display_name || user.email}</span>
          <button type="button" className="button-link" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  );
}

// Auth gate for the whole app: it fetches the current user, shows the loading
// and login screens, and only then renders the routed views (via <Outlet>).
// It is the router's root layout route so that every view — including the
// editor's useBlocker — runs inside the data router.
function RootGate() {
  const [user, setUser] = useState<AuthUser | null>();
  const location = useLocation();

  useEffect(() => {
    let active = true;
    getCurrentUser().then(
      (current) => {
        if (active) setUser(current);
      },
      (error: unknown) => {
        if (active && error instanceof ApiError && error.status === 401) setUser(null);
        else if (active) setUser(null);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  if (user === undefined) {
    return <main className="auth-screen">Loading SaReGaMaPic…</main>;
  }
  if (user === null) {
    const returnTo = `${location.pathname}${location.search}`;
    return (
      <main className="auth-screen">
        <h1>SaReGaMaPic</h1>
        <p>Point. Shoot. Sa Re Ga Ma.</p>
        <a
          className="primary-button"
          href={`/api/auth/login?return_to=${encodeURIComponent(returnTo)}`}
        >
          Continue with Google
        </a>
        <p className="auth-note">Access is limited to invited accounts.</p>
      </main>
    );
  }
  const context: AppContext = { user, onSignedOut: () => setUser(null) };
  return <Outlet context={context} />;
}

// Shared route tree — createBrowserRouter in main.tsx (prod) and
// createMemoryRouter in tests both build a data router from this, so useBlocker
// works in both.
export const routes = createRoutesFromElements(
  <Route element={<RootGate />}>
    <Route element={<Shell />}>
      <Route path="/" element={<SongsPage />} />
      <Route path="/songs/:songId" element={<SongPage />} />
    </Route>
    <Route path="/songs/:songId/pages/:pageNo" element={<PageViewer />} />
    <Route path="/songs/:songId/pages/:pageNo/edit" element={<EditorPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route>,
);
