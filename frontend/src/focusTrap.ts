import { useEffect, type RefObject } from "react";

// Tabbable descendants of a dialog. `:not([disabled])` matters here: the
// unsaved-changes modal disables all three buttons while a save is in flight, so
// the set can legitimately be empty and the trap must cope (keep focus on the
// container rather than let Tab escape).
const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), ' +
  'select:not([disabled]), [tabindex]:not([tabindex="-1"])';

function focusable(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE));
}

/**
 * Focus management for a modal dialog (codebase-review finding #17). While
 * `active`, it:
 *   1. moves focus into the dialog (the container itself, which the caller marks
 *      `tabIndex={-1}`), so the dialog's own Escape/keyboard handlers actually
 *      receive keys — previously focus never entered, so Escape was dead;
 *   2. traps Tab / Shift+Tab so focus cycles within the dialog and cannot reach
 *      the page behind an `aria-modal` overlay;
 *   3. restores focus to whatever was focused before it opened (the trigger),
 *      so keyboard users are not dumped at the top of the page on close.
 *
 * The container element is focused rather than a specific button so the choice
 * of default action stays with the markup, and no key press lands on the
 * destructive "Discard" by accident. Tab from the container then reaches the
 * first control by normal document order.
 */
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const container = ref.current;
    if (!container) return;

    // Remember where focus was so we can hand it back on close. Guard the type:
    // document.activeElement is Element, but only HTMLElement has focus().
    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    container.focus();

    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Tab" || !container) return;
      const items = focusable(container);
      const current = document.activeElement;
      const first = items[0];
      const last = items[items.length - 1];
      // No tabbable control (e.g. every button disabled mid-save): pin focus to
      // the container so Tab can't leave the dialog.
      if (!first || !last) {
        event.preventDefault();
        container.focus();
        return;
      }
      if (event.shiftKey) {
        // Backward off the first control — or from the container / anywhere that
        // has slipped outside — wraps to the last.
        if (current === first || current === container || !container.contains(current)) {
          event.preventDefault();
          last.focus();
        }
      } else {
        // Forward off the last control, or from outside, goes to the first.
        // Forward from the container falls through to normal order (→ first).
        if (current === last || !container.contains(current)) {
          event.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [ref, active]);
}
