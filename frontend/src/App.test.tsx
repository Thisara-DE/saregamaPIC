import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { AuthUser, Song, SongDetail } from "./api/types";

const authUser: AuthUser = {
  id: "user1",
  email: "thisara@example.com",
  display_name: "Thisara",
};

const song: Song = {
  id: "abc123",
  title: "Test Sinhala Song",
  notes: "",
  created_at: "2026-07-17T00:00:00Z",
  scan_count: 2,
  cover_scan_id: "scan1",
};

const songs: Song[] = [song];

const detail: SongDetail = {
  ...song,
  scans: [
    {
      id: "scan1",
      song_id: "abc123",
      page_no: 1,
      content_type: "image/jpeg",
      uploaded_at: "2026-07-17T00:00:00Z",
    },
    {
      id: "scan2",
      song_id: "abc123",
      page_no: 2,
      content_type: "image/jpeg",
      uploaded_at: "2026-07-17T00:00:00Z",
    },
  ],
};

function mockFetchJson(body: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    const responseBody = url === "/api/auth/me" ? authUser : body;
    return Promise.resolve(
      new Response(JSON.stringify(responseBody), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: vi.fn(() => "blob:sheet-preview"),
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("lists songs with cover thumbnails in the gallery", async () => {
    vi.stubGlobal("fetch", mockFetchJson(songs));
    renderAt("/");
    await waitFor(() => {
      expect(screen.getByText("SaReGaMaPic")).toBeInTheDocument();
      expect(screen.getByText("Test Sinhala Song")).toBeInTheDocument();
    });
    expect(screen.getByText("2 pages")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Test Sinhala Song/ })).toHaveAttribute(
      "href",
      "/songs/abc123",
    );
  });

  it("starts a new song with an image and an optional title", async () => {
    const imported = {
      song: { ...song, id: "new-song", title: "", scan_count: 1, cover_scan_id: "new-scan" },
      scan: { ...detail.scans[0], id: "new-scan", song_id: "new-song", page_no: 1 },
    };
    let importBody: FormData | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/auth/me") return Promise.resolve(Response.json(authUser));
        if (url === "/api/songs/import") {
          importBody = init?.body as FormData;
          return Promise.resolve(Response.json(imported, { status: 201 }));
        }
        if (url === "/api/songs/new-song") {
          return Promise.resolve(Response.json({ ...imported.song, scans: [imported.scan] }));
        }
        if (url === "/api/scans/new-scan/transcription") {
          return Promise.resolve(Response.json({ detail: "Not found" }, { status: 404 }));
        }
        return Promise.resolve(Response.json(songs));
      }),
    );
    renderAt("/");
    await screen.findByRole("button", { name: "Choose image…" });

    const inputs = document.querySelectorAll<HTMLInputElement>('input[type="file"]');
    const file = new File(["sheet"], "sheet.jpg", { type: "image/jpeg" });
    const browseInput = inputs[1];
    expect(browseInput).toBeDefined();
    fireEvent.change(browseInput!, { target: { files: [file] } });
    expect(await screen.findByRole("img", { name: "Selected sheet preview" })).toHaveAttribute(
      "src",
      "blob:sheet-preview",
    );
    fireEvent.change(screen.getByLabelText(/Song name/), {
      target: { value: "My optional name" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add song" }));

    await waitFor(() => expect(importBody).toBeDefined());
    expect(importBody?.get("file")).toBe(file);
    expect(importBody?.get("title")).toBe("My optional name");
    await screen.findByText("Untitled song — page 1");
  });

  it("song page shows thumbnails linking to the page viewer", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail));
    renderAt("/songs/abc123");
    await waitFor(() => {
      expect(screen.getByText("Test Sinhala Song")).toBeInTheDocument();
    });
    const page1 = screen.getByRole("img", { name: "Page 1" });
    expect(page1).toHaveAttribute("src", "/api/scans/scan1/thumbnail");
    expect(page1.closest("a")).toHaveAttribute("href", "/songs/abc123/pages/1");
    expect(screen.getByRole("button", { name: /Photograph sheet/ })).toBeInTheDocument();
  });

  it("viewer shows the ORIGINAL photo, not the thumbnail", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail));
    renderAt("/songs/abc123/pages/2");
    await waitFor(() => {
      expect(screen.getByText("Test Sinhala Song — 2 / 2")).toBeInTheDocument();
    });
    expect(screen.getByRole("img", { name: /Page 2 of/ })).toHaveAttribute(
      "src",
      "/api/scans/scan2/image",
    );
    // page 2 of 2 → only a "previous" arrow
    expect(screen.getByRole("button", { name: "Previous page" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Next page" })).not.toBeInTheDocument();
  });

  it("shows API errors instead of crashing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/auth/me") {
          return Promise.resolve(Response.json(authUser));
        }
        return Promise.resolve(
          new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
        );
      }),
    );
    renderAt("/");
    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
  });

  it("offers Google login when the session is missing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }),
      ),
    );
    renderAt("/songs/abc123");
    const login = await screen.findByRole("link", { name: "Continue with Google" });
    expect(login).toHaveAttribute(
      "href",
      "/api/auth/login?return_to=%2Fsongs%2Fabc123",
    );
  });
});
