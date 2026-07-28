import { useEffect, useState } from "react";
import {
  createRoutesFromElements,
  Navigate,
  Outlet,
  Route,
  useLocation,
  useOutletContext,
  useRouteError,
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
  const [loadError, setLoadError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const location = useLocation();

  useEffect(() => {
    let active = true;
    setUser(undefined);
    setLoadError(null);
    getCurrentUser().then(
      (current) => {
        if (active) setUser(current);
      },
      (error: unknown) => {
        if (!active) return;
        // Only a 401 means "not signed in" → show the login screen. A 500, or a
        // network failure (offline surfaces as TypeError, not ApiError), must
        // NOT masquerade as signed-out — that bounced a logged-in user to the
        // login screen on any transient server/connectivity hiccup (finding 9).
        if (error instanceof ApiError && error.status === 401) {
          setUser(null);
        } else {
          setLoadError(error instanceof Error ? error.message : "Something went wrong.");
        }
      },
    );
    return () => {
      active = false;
    };
  }, [attempt]);

  if (loadError !== null) {
    return (
      <main className="auth-screen">
        <h1>SaReGaMaPic</h1>
        <p className="error">Couldn’t reach the server.</p>
        <p className="auth-note">{loadError}</p>
        <button
          type="button"
          className="primary-button"
          onClick={() => setAttempt((n) => n + 1)}
        >
          Try again
        </button>
      </main>
    );
  }
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

// Error boundary for the whole route tree. A data router catches a render/loader
// throw and renders the nearest route's errorElement instead of unmounting to a
// blank page (finding 8); this is that fallback. A class boundary around
// <RouterProvider> would not help — RouterProvider handles route errors itself
// and does not re-throw them to a parent boundary.
export function RouteErrorPage() {
  const error = useRouteError();
  const message =
    error instanceof Error ? error.message : typeof error === "string" ? error : "";
  return (
    <main className="auth-screen">
      <h1>SaReGaMaPic</h1>
      <p className="error">Something went wrong.</p>
      {message ? <p className="auth-note">{message}</p> : null}
      <button
        type="button"
        className="primary-button"
        onClick={() => window.location.reload()}
      >
        Reload
      </button>
    </main>
  );
}

// Shared route tree — createBrowserRouter in main.tsx (prod) and
// createMemoryRouter in tests both build a data router from this, so useBlocker
// works in both.
export const routes = createRoutesFromElements(
  <Route element={<RootGate />} errorElement={<RouteErrorPage />}>
    <Route element={<Shell />}>
      <Route path="/" element={<SongsPage />} />
      <Route path="/songs/:songId" element={<SongPage />} />
    </Route>
    <Route path="/songs/:songId/pages/:pageNo" element={<PageViewer />} />
    <Route path="/songs/:songId/pages/:pageNo/edit" element={<EditorPage />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Route>,
);
