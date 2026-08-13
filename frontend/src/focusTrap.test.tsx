import { render, screen } from "@testing-library/react";
import { useRef } from "react";
import { describe, expect, it } from "vitest";
import { useFocusTrap } from "./focusTrap";

// A minimal harness: a "trigger" button outside the dialog (to prove focus is
// restored to it) and a dialog with two buttons plus one that can be disabled.
function Harness({ active, disableSecond = false }: { active: boolean; disableSecond?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useFocusTrap(ref, active);
  return (
    <div>
      <button type="button">trigger</button>
      {active && (
        <div ref={ref} role="alertdialog" tabIndex={-1} aria-label="dlg">
          <button type="button">first</button>
          <button type="button" disabled={disableSecond}>
            second
          </button>
        </div>
      )}
    </div>
  );
}

function tab(shiftKey = false) {
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", shiftKey, bubbles: true }));
}

describe("useFocusTrap", () => {
  it("moves focus onto the dialog when it opens", () => {
    render(<Harness active />);
    expect(screen.getByRole("alertdialog")).toHaveFocus();
  });

  it("wraps Tab from the last control back to the first", () => {
    render(<Harness active />);
    const first = screen.getByRole("button", { name: "first" });
    const last = screen.getByRole("button", { name: "second" });
    last.focus();
    tab();
    expect(first).toHaveFocus();
  });

  it("wraps Shift+Tab from the first control to the last", () => {
    render(<Harness active />);
    const first = screen.getByRole("button", { name: "first" });
    const last = screen.getByRole("button", { name: "second" });
    first.focus();
    tab(true);
    expect(last).toHaveFocus();
  });

  it("Shift+Tab from the dialog container wraps to the last control", () => {
    render(<Harness active />);
    const dialog = screen.getByRole("alertdialog");
    const last = screen.getByRole("button", { name: "second" });
    dialog.focus();
    tab(true);
    expect(last).toHaveFocus();
  });

  it("skips a disabled control when wrapping", () => {
    render(<Harness active disableSecond />);
    const first = screen.getByRole("button", { name: "first" });
    // Only "first" is tabbable now, so it is both first and last: Tab wraps to it.
    first.focus();
    tab();
    expect(first).toHaveFocus();
  });

  it("restores focus to the trigger when the dialog closes", () => {
    const { rerender } = render(<Harness active={false} />);
    const trigger = screen.getByRole("button", { name: "trigger" });
    trigger.focus();
    expect(trigger).toHaveFocus();

    rerender(<Harness active />);
    expect(screen.getByRole("alertdialog")).toHaveFocus();

    rerender(<Harness active={false} />);
    expect(trigger).toHaveFocus();
  });
});
