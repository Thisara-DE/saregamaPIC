import { useOnlineStatus } from "../offline";

/**
 * A fixed pill that appears only while offline (finding #16). It tells the
 * reader that what they see is the last-cached copy — so a stale sheet is
 * understood as cached rather than mistaken for live, and a failed write is not
 * a mystery. Renders nothing when online, so it costs no layout in normal use;
 * being `position: fixed`, it also costs none when shown. Safe to mount on more
 * than one route — only the active route is ever mounted at a time.
 */
export function OfflineBanner() {
  const online = useOnlineStatus();
  if (online) return null;
  return (
    <div className="offline-banner" role="status">
      <span aria-hidden="true">⚡</span> Offline — showing saved copies
    </div>
  );
}
