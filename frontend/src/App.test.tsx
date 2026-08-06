import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RouteErrorPage, routes } from "./App";
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
  digital_page_no: null,
  status: "new",
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
      status: "new",
    },
    {
      id: "scan2",
      song_id: "abc123",
      page_no: 2,
      content_type: "image/jpeg",
      uploaded_at: "2026-07-17T00:00:00Z",
      status: "new",
    },
  ],
};

// `transcription` omitted = the page has none yet, so the endpoint 404s. Without
// this the mock answered the transcription request with the SongDetail body,
// which no longer resembles a Transcription closely enough to be safe.
function mockFetchJson(body: unknown, transcription?: unknown) {
  return vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    if (url === "/api/auth/me") return Promise.resolve(Response.json(authUser));
    if (url.endsWith("/transcription")) {
      return Promise.resolve(
        transcription === undefined
          ? new Response(JSON.stringify({ detail: "No transcription for this scan yet" }), {
              status: 404,
              headers: { "Content-Type": "application/json" },
            })
          : Response.json(transcription),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
}

const digitalTranscription = {
  id: "t1",
  scan_id: "scan2",
  status: "reviewed",
  stf: {
    header: { concert_scale: "G", alto_scale: "E", beat: "4/4" },
    lines: [{ n: 1, kind: "sargam", text: "S R - G | P D N S'" }],
  },
  warnings: [],
  model: null,
  input_tokens: null,
  output_tokens: null,
  updated_at: "2026-07-23T00:00:00Z",
};

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear(); // the digital text-size preference persists here
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

  it("renames a song recognition left untitled", async () => {
    // The gap this closes: a song recognition never named had no title editor
    // anywhere in the app, so it was stuck as "Untitled song" permanently.
    const untitled: Song = { ...song, title: "", digital_page_no: null };
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      if (url === "/api/auth/me") return Promise.resolve(Response.json(authUser));
      if (init?.method === "PATCH") {
        const sent = JSON.parse(String(init.body)) as { title: string };
        return Promise.resolve(Response.json({ ...untitled, title: sent.title }));
      }
      return Promise.resolve(Response.json([untitled]));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/");

    await screen.findByText("Untitled song");
    fireEvent.click(screen.getByRole("button", { name: /Actions for Untitled song/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("Song name"), {
      target: { value: "  Tharuda Nidana  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await screen.findByText("Tharuda Nidana");
    const patch = fetchMock.mock.calls.find(
      (call) => (call[1] as RequestInit | undefined)?.method === "PATCH",
    );
    expect(patch?.[0]).toBe("/api/songs/abc123");
    // Trimmed client-side before it is sent; the server trims again as defence.
    expect(JSON.parse(String((patch?.[1] as RequestInit).body))).toEqual({
      title: "Tharuda Nidana",
    });
  });

  it("keeps the menu open when a menu item is pressed (pointerdown must not dismiss it)", async () => {
    // Regression: the outside-tap dismiss listened on pointerdown and fired for
    // taps INSIDE the menu too. Pointerdown precedes click, so it tore the menu
    // down before the item's click could land — every option silently did
    // nothing. A real tap is pointerdown → click; the click-only tests missed it.
    vi.stubGlobal("fetch", mockFetchJson([{ ...song, title: "", digital_page_no: null }]));
    renderAt("/");
    await screen.findByText("Untitled song");

    fireEvent.click(screen.getByRole("button", { name: /Actions for Untitled song/ }));
    const renameItem = screen.getByRole("menuitem", { name: "Rename" });
    // Faithfully replay the browser's order: pointerdown, then the click.
    fireEvent.pointerDown(renameItem);
    expect(screen.getByRole("menuitem", { name: "Rename" })).toBeInTheDocument(); // survived
    fireEvent.click(renameItem);

    // The inline rename form opened, proving the item's click actually ran.
    expect(screen.getByLabelText("Song name")).toBeInTheDocument();
  });

  it("closes the menu on a tap outside it", async () => {
    vi.stubGlobal("fetch", mockFetchJson(songs));
    renderAt("/");
    await screen.findByText("Test Sinhala Song");

    fireEvent.click(screen.getByRole("button", { name: /Actions for Test Sinhala Song/ }));
    expect(screen.getByRole("menuitem", { name: "Rename" })).toBeInTheDocument();
    fireEvent.pointerDown(document.body);
    await waitFor(() => {
      expect(screen.queryByRole("menuitem", { name: "Rename" })).not.toBeInTheDocument();
    });
  });

  it("disables the digital menu options until there is something to open", async () => {
    const untranscribed: Song = { ...song, digital_page_no: null };
    vi.stubGlobal("fetch", mockFetchJson([untranscribed]));
    renderAt("/");
    await screen.findByText("Test Sinhala Song");

    fireEvent.click(screen.getByRole("button", { name: /Actions for Test Sinhala Song/ }));
    expect(screen.getByRole("menuitem", { name: "Open digital version" })).toBeDisabled();
    // Editing stays available — that is how the first transcription gets made.
    expect(screen.getByRole("menuitem", { name: "Edit digital version" })).toBeEnabled();
    expect(screen.getByRole("menuitem", { name: "Delete song" })).toBeInTheDocument();
  });

  it("opens the digital version straight from the song card once one exists", async () => {
    // The gallery lists songs; the viewer then needs the song DETAIL, so this
    // mock has to answer both shapes rather than one body for every URL.
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/auth/me") return Promise.resolve(Response.json(authUser));
        if (url === "/api/songs") {
          return Promise.resolve(Response.json([{ ...song, digital_page_no: 2 }]));
        }
        if (url.endsWith("/transcription")) {
          return Promise.resolve(Response.json(digitalTranscription));
        }
        return Promise.resolve(Response.json({ ...detail, digital_page_no: 2 }));
      }),
    );
    renderAt("/");
    await screen.findByText("Test Sinhala Song");

    fireEvent.click(screen.getByRole("button", { name: /Actions for Test Sinhala Song/ }));
    const open = screen.getByRole("menuitem", { name: "Open digital version" });
    expect(open).toBeEnabled();
    fireEvent.click(open);
    // Lands on the page that actually holds the transcription, not page 1.
    await screen.findByText("Test Sinhala Song — 2 / 2");
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

  it("viewer opens on the digital version when the page has one", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    renderAt("/songs/abc123/pages/2");
    await screen.findByText("Test Sinhala Song — 2 / 2");
    // Reaching the page should not cost a second tap to see the notation.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Digital" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });
    expect(screen.getByText("Concert G")).toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /Page 2 of/ })).not.toBeInTheDocument();
    // The photo is still one tap away — the fidelity rule's original.
    fireEvent.click(screen.getByRole("button", { name: "Original" }));
    // #15: the 1600px preview paints first, then the full-res original swaps in
    // once it loads.
    expect(screen.getByRole("img", { name: /Page 2 of/ })).toHaveAttribute(
      "src",
      "/api/scans/scan2/preview",
    );
    fireEvent.load(document.querySelector('img[src="/api/scans/scan2/image"]')!);
    expect(screen.getByRole("img", { name: /Page 2 of/ })).toHaveAttribute(
      "src",
      "/api/scans/scan2/image",
    );
  });

  it("steps the digital text size and persists the choice", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    const digital = container.querySelector(".viewer-digital") as HTMLElement;
    const larger = screen.getByRole("button", { name: "Larger text" });
    const smaller = screen.getByRole("button", { name: "Smaller text" });

    // Opens at 100% = the unscaled default.
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(digital.style.getPropertyValue("--digital-scale")).toBe("1");

    fireEvent.click(larger);
    expect(screen.getByText("125%")).toBeInTheDocument();
    expect(digital.style.getPropertyValue("--digital-scale")).toBe("1.25");
    // Persisted so the music-stand size survives a page change / app restart.
    expect(localStorage.getItem("saregamapic.digitalScale")).toBe("1.25");

    fireEvent.click(smaller);
    expect(screen.getByText("100%")).toBeInTheDocument();
    expect(localStorage.getItem("saregamapic.digitalScale")).toBe("1");
  });

  it("disables the smaller-text button at the minimum size", async () => {
    localStorage.setItem("saregamapic.digitalScale", "0.8"); // smallest step
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    // The persisted preference is restored, not reset to 100%.
    expect(screen.getByText("80%")).toBeInTheDocument();
    const digital = container.querySelector(".viewer-digital") as HTMLElement;
    expect(digital.style.getPropertyValue("--digital-scale")).toBe("0.8");
    expect(screen.getByRole("button", { name: "Smaller text" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Larger text" })).toBeEnabled();
  });

  it("toggles the viewer between night and day themes and persists the choice", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    const viewer = container.querySelector(".viewer") as HTMLElement;
    const dayBtn = screen.getByRole("button", { name: "Day theme" });

    // Night is the default — the viewer has always looked this way.
    expect(viewer).toHaveClass("theme-night");
    expect(dayBtn).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(dayBtn);
    expect(viewer).toHaveClass("theme-day");
    expect(viewer).not.toHaveClass("theme-night");
    expect(dayBtn).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("saregamapic.viewerTheme")).toBe("day");

    fireEvent.click(dayBtn);
    expect(viewer).toHaveClass("theme-night");
    expect(localStorage.getItem("saregamapic.viewerTheme")).toBe("night");
  });

  // Finding F3: the theme repaints the whole viewer and persists, so its toggle
  // must not be gated on the digital controls row — a page with no transcription
  // renders no row, and used to open day-themed with no way back.
  it("keeps the theme toggle reachable on a page with no transcription", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail)); // no transcription -> 404
    const { container } = renderAt("/songs/abc123/pages/1");
    await screen.findByText("Test Sinhala Song — 1 / 2");

    // No Digital view to configure: no controls row, no text-size stepper.
    expect(container.querySelector(".digital-controls")).toBeNull();
    expect(screen.queryByRole("button", { name: "Larger text" })).not.toBeInTheDocument();

    // The theme toggle is still there, and still works.
    const dayBtn = screen.getByRole("button", { name: "Day theme" });
    fireEvent.click(dayBtn);
    expect(container.querySelector(".viewer")).toHaveClass("theme-day");
    expect(dayBtn).toHaveAttribute("aria-pressed", "true");
  });

  it("restores a persisted day theme, and keeps it across a page change", async () => {
    localStorage.setItem("saregamapic.viewerTheme", "day");
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    expect(container.querySelector(".viewer")).toHaveClass("theme-day");
    expect(screen.getByRole("button", { name: "Day theme" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // Unlike key/octave, the theme is a reading preference: navigating to
    // another page must NOT reset it back to night.
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByText("Test Sinhala Song — 1 / 2");
    expect(container.querySelector(".viewer")).toHaveClass("theme-day");
  });

  it("viewer shows the ORIGINAL photo, not the thumbnail", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail));
    renderAt("/songs/abc123/pages/2");
    await waitFor(() => {
      expect(screen.getByText("Test Sinhala Song — 2 / 2")).toBeInTheDocument();
    });
    // #15: the preview paints first (never the thumbnail), then the full-res
    // original swaps in once it loads.
    expect(screen.getByRole("img", { name: /Page 2 of/ })).toHaveAttribute(
      "src",
      "/api/scans/scan2/preview",
    );
    fireEvent.load(document.querySelector('img[src="/api/scans/scan2/image"]')!);
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

  it("shows a retryable error, NOT the login screen, when the session check 500s", async () => {
    // Finding 9: a 500 on /api/auth/me must not masquerade as "signed out".
    let meCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/auth/me") {
          meCalls += 1;
          if (meCalls === 1) {
            return Promise.resolve(
              new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
            );
          }
          return Promise.resolve(Response.json(authUser));
        }
        return Promise.resolve(Response.json(songs));
      }),
    );
    renderAt("/");

    await screen.findByText("Couldn’t reach the server.");
    expect(
      screen.queryByRole("link", { name: "Continue with Google" }),
    ).not.toBeInTheDocument();

    // Retry re-runs the session check; the second call succeeds → app loads.
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText("Test Sinhala Song");
  });

  it("shows the error screen (not login) when the session check fails at the network layer", async () => {
    // Offline: fetch rejects with a TypeError — not an ApiError 401 — so the
    // old both-branches-set-null code wrongly bounced the user to login.
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/auth/me") return Promise.reject(new TypeError("Failed to fetch"));
        return Promise.resolve(Response.json(songs));
      }),
    );
    renderAt("/");

    await screen.findByText("Couldn’t reach the server.");
    expect(
      screen.queryByRole("link", { name: "Continue with Google" }),
    ).not.toBeInTheDocument();
  });

  it("wires the error boundary onto the root route", () => {
    // Finding 8: the real route tree must carry the fallback, not only the
    // isolated render below.
    expect(routes[0]?.errorElement).toBeTruthy();
  });

  it("renders a fallback instead of blanking when a route throws", () => {
    // React logs the caught error; silence it so the run output stays clean.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const Boom = () => {
      throw new Error("render kaboom");
    };
    const router = createMemoryRouter(
      [{ path: "/", element: <Boom />, errorElement: <RouteErrorPage /> }],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);

    expect(screen.getByText("Something went wrong.")).toBeInTheDocument();
    expect(screen.getByText("render kaboom")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    spy.mockRestore();
  });

  it("catches a REAL page render throw with the wired errorElement, not just a synthetic route", async () => {
    // Exercises the actual tree: RootGate auth is satisfied, then SongsPage
    // renders and throws because /api/songs resolves 200 with a non-array, so
    // `songs?.map` blows up during render — uncaught by the page's fetch
    // `.catch`, so it must bubble to the root route's errorElement (finding 8).
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/auth/me") return Promise.resolve(Response.json(authUser));
        return Promise.resolve(Response.json({ not: "an array" }));
      }),
    );
    renderAt("/");

    await screen.findByText("Something went wrong.");
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
    // The gallery was replaced, not augmented — its controls never committed.
    expect(screen.queryByRole("button", { name: "Choose image…" })).not.toBeInTheDocument();
    spy.mockRestore();
  });
});
