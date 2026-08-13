import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../App";
import type { AdminUser, AuthUser } from "../api/types";

const owner: AuthUser = {
  id: "00000000000000000000000000000001",
  email: "owner@example.com",
  display_name: "Owner",
  is_admin: true,
};

const nonAdmin: AuthUser = { ...owner, id: "u2", email: "friend@example.com", is_admin: false };

const existingUsers: AdminUser[] = [
  {
    id: "00000000000000000000000000000001",
    email: "owner@example.com",
    display_name: "Owner",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
  },
];

// Mock fetch: /api/auth/me returns `me`; GET /api/auth/users returns the list;
// POST /api/auth/users echoes an invited user (or a 409/422 error when asked).
function mockFetch(me: AuthUser, opts: { inviteStatus?: number; inviteDetail?: string } = {}) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url === "/api/auth/me") return Promise.resolve(Response.json(me));
    if (url === "/api/auth/users" && init?.method === "POST") {
      if (opts.inviteStatus && opts.inviteStatus >= 400) {
        return Promise.resolve(
          new Response(JSON.stringify({ detail: opts.inviteDetail ?? "nope" }), {
            status: opts.inviteStatus,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      const email = (JSON.parse(String(init?.body)) as { email: string }).email;
      const created: AdminUser = {
        id: "new1",
        email,
        display_name: "",
        status: "invited",
        created_at: "2026-02-02T00:00:00Z",
      };
      return Promise.resolve(Response.json(created, { status: 201 }));
    }
    if (url === "/api/auth/users") return Promise.resolve(Response.json(existingUsers));
    // Songs list, for the "/" redirect landing.
    return Promise.resolve(Response.json([]));
  });
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("AdminPage / access management (finding #18)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("shows the admin the 'Manage access' link; a non-admin does not get it", async () => {
    vi.stubGlobal("fetch", mockFetch(owner));
    renderAt("/");
    expect(await screen.findByRole("link", { name: "Manage access" })).toBeInTheDocument();
  });

  it("hides the link from a non-admin", async () => {
    vi.stubGlobal("fetch", mockFetch(nonAdmin));
    renderAt("/");
    await screen.findByText("SaReGaMaPic");
    expect(screen.queryByRole("link", { name: "Manage access" })).not.toBeInTheDocument();
  });

  it("lists existing users and invites a new email", async () => {
    vi.stubGlobal("fetch", mockFetch(owner));
    renderAt("/people");

    // Existing user is listed (wait on the status pill — "Owner" also appears in
    // the header account menu, so it's not list-specific).
    expect(await screen.findByText("Active")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Email to invite"), {
      target: { value: "friend@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));

    // The new invite is confirmed and appended to the list with an Invited pill.
    expect(await screen.findByText(/Invited friend@example.com/)).toBeInTheDocument();
    expect(screen.getByText("Invited")).toBeInTheDocument();
  });

  it("surfaces a 409 conflict from the API", async () => {
    vi.stubGlobal(
      "fetch",
      mockFetch(owner, { inviteStatus: 409, inviteDetail: "That email already has active access." }),
    );
    renderAt("/people");
    await screen.findByText("Active");

    fireEvent.change(screen.getByLabelText("Email to invite"), {
      target: { value: "owner@example.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send invite" }));

    expect(await screen.findByText("That email already has active access.")).toBeInTheDocument();
  });

  it("redirects a non-admin who navigates to /people straight back home", async () => {
    vi.stubGlobal("fetch", mockFetch(nonAdmin));
    renderAt("/people");
    // Landing on "/" renders the gallery's upload heading; no admin chrome.
    await screen.findByText("Upload a new song");
    expect(screen.queryByText("Manage access")).not.toBeInTheDocument();
  });
});
