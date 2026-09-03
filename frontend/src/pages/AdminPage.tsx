import { useEffect, useState } from "react";
import { Link, Navigate, useOutletContext } from "react-router-dom";
import { ApiError, inviteUser, listUsers } from "../api/client";
import type { ShellContext } from "../App";
import type { AdminUser } from "../api/types";

/**
 * Access management (finding #18): the admin (the initial owner) adds an email to
 * the invite allowlist here instead of hand-editing SQLite on the volume. The
 * invited person can then sign in with Google. Non-admins are turned away by the
 * backend (403); this page surfaces that rather than pretending to work.
 */
export function AdminPage() {
  const { user } = useOutletContext<ShellContext>();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invited, setInvited] = useState<string | null>(null);

  useEffect(() => {
    if (!user.is_admin) return;
    listUsers()
      .then(setUsers)
      .catch((e: unknown) => setLoadError(e instanceof Error ? e.message : String(e)));
  }, [user.is_admin]);

  // A non-admin who typed the URL directly: send them home. The backend refuses
  // the endpoints regardless; this just avoids rendering admin chrome they can't
  // use. (Placed after the hooks so their order stays stable.)
  if (!user.is_admin) return <Navigate to="/" replace />;

  async function handleInvite(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = email.trim();
    if (!trimmed || busy) return;
    setBusy(true);
    setError(null);
    setInvited(null);
    try {
      const created = await inviteUser(trimmed);
      // Keep the list ordered like the API (created_at, email) — a new invite is
      // the newest row, so it appends.
      setUsers((current) => [...(current ?? []), created]);
      setInvited(created.email);
      setEmail("");
    } catch (e) {
      // 409 (already has access) and 422 (malformed) both carry a readable
      // detail from the API; show it as-is.
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="page-toolbar">
        <Link className="back" to="/">
          ← Songs
        </Link>
      </div>
      <h2>Manage access</h2>
      <p className="muted">
        Add someone’s Google email to invite them. They’ll be able to sign in and keep their
        own private songs.
      </p>

      <form className="capture-actions" onSubmit={handleInvite}>
        <label className="sr-only" htmlFor="invite-email">
          Email to invite
        </label>
        <input
          id="invite-email"
          type="email"
          inputMode="email"
          autoComplete="off"
          placeholder="name@example.com"
          value={email}
          maxLength={254}
          onChange={(e) => setEmail(e.target.value)}
        />
        <button className="primary" type="submit" disabled={busy || !email.trim()}>
          {busy ? "Inviting…" : "Send invite"}
        </button>
      </form>

      {invited && <p className="muted">Invited {invited}. They can sign in now.</p>}
      {error && <p className="error">{error}</p>}
      {loadError && <p className="error">{loadError}</p>}

      {users !== null && (
        <ul className="song-list access-list">
          {users.map((u) => (
            <li key={u.id} className="song-card">
              <div className="song-row">
                <span className="song-heading">
                  <span className="song-title">{u.display_name || u.email}</span>
                  <span className={`status-pill ${u.status === "active" ? "reviewed" : ""}`}>
                    {u.status === "active"
                      ? "Active"
                      : u.status === "invited"
                        ? "Invited"
                        : "Disabled"}
                  </span>
                </span>
                {u.display_name ? <span className="muted">{u.email}</span> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
