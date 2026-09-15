import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RouteErrorPage, routes } from "./App";
import type { AuthUser, Song, SongDetail } from "./api/types";
import { RUNTIME_CACHES } from "./swCache";

const authUser: AuthUser = {
  id: "user1",
  email: "thisara@example.com",
  display_name: "Thisara",
  is_admin: false,
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
    // "What are you playing?" fires once per playing session and would otherwise
    // open over every digital-view test, in an order-dependent way (sessionStorage
    // outlives a single test). Clear it for isolation, then answer it: these
    // tests are about the steady state. The tests that exercise the prompt
    // itself clear this key again.
    sessionStorage.clear();
    sessionStorage.setItem("saregamapic.instrumentAsked", "1");
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

  // --- Phase 3.6: instrument profiles -------------------------------------
  //
  // Reads the notes off the screen the way a player does: `.stf-note` renders
  // the accidental as a class and the octave as dots, so reconstruct the token
  // from what is actually painted rather than trusting an internal string.
  function renderedNotes(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll(".digital-lines .stf-note")).map((note) => {
      const letter = note.querySelector(".stf-letter")?.textContent ?? "";
      const accidental = note.classList.contains("flat")
        ? "♭"
        : note.classList.contains("sharp")
          ? "♯"
          : "";
      const above = (note.querySelector(".stf-dots.above")?.textContent ?? "").trim();
      const below = (note.querySelector(".stf-dots.below")?.textContent ?? "").trim();
      return letter + accidental + "'".repeat(above.length) + ",".repeat(below.length);
    });
  }

  it("shows a sheet verbatim on the Alto Sax — the profile the letters are stored in", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    expect(screen.getByText("Alto E")).toBeInTheDocument();
    expect(renderedNotes(container)).toEqual(["S", "R", "G", "P", "D", "N", "S'"]);
    // Nothing is derived, so there is nothing to reset or nudge.
    expect(screen.queryByRole("button", { name: "Reset" })).not.toBeInTheDocument();
  });

  it("re-fingers the same sheet for a D flute and keeps it in concert G", async () => {
    // The user's worked example (2026-09-08): Concert G / Alto E on a flute
    // whose S sounds concert D. The tune must not move — the fingers do.
    localStorage.setItem("saregamapic.instrument", "bamboo-flute:2");
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    expect(screen.getByText("Flute D · tonic M")).toBeInTheDocument();
    expect(screen.queryByText("Alto E")).not.toBeInTheDocument();
    expect(renderedNotes(container)).toEqual(["D♭,", "N♭,", "S", "G♭", "M", "P", "D♭"]);
    // The key has NOT changed, so the view carries no "transposed" tag — but it
    // is derived, so the octave nudge is available for a flute's register.
    expect(screen.queryByText(/transposed/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /8va▲/ })).toBeInTheDocument();
  });

  it("switches instrument live, and remembers it for the next session", async () => {
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    fireEvent.change(screen.getByLabelText("Instrument"), { target: { value: "bamboo-flute:7" } });

    // A G flute plays a concert-G tune from S — the easy case the user picks a
    // flute for. Same sounding music, different fingerings.
    expect(screen.getByText("Flute G · tonic S")).toBeInTheDocument();
    expect(renderedNotes(container)).toEqual(["G♭", "M", "P", "N♭", "S'", "R'", "G♭'"]);
    expect(localStorage.getItem("saregamapic.instrument")).toBe("bamboo-flute:7");
  });

  it("keeps the instrument across a page change — you do not put the flute down", async () => {
    localStorage.setItem("saregamapic.instrument", "bamboo-flute:2");
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    renderAt("/songs/abc123/pages/2");
    await screen.findByText("Flute D · tonic M");

    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByText("Test Sinhala Song — 1 / 2");
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("Flute D · tonic M");
  });

  it("transposes on top of the flute's fingering when a new key is chosen", async () => {
    localStorage.setItem("saregamapic.instrument", "bamboo-flute:2");
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    // Ask for concert C on the D flute: now the music DOES move, so the header
    // follows it and the transposed tag appears.
    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "0" } });
    expect(screen.getByText("Concert C")).toBeInTheDocument();
    // Concert C on a D flute is fingered from N♭ — exactly the awkward case the
    // user said they would answer by reaching for a different flute.
    expect(screen.getByText("Flute D · tonic N♭")).toBeInTheDocument();
    expect(screen.getByText(/transposed/)).toBeInTheDocument();
    expect(renderedNotes(container)).toEqual(["R♭", "G♭", "M", "D♭", "N♭", "S'", "R♭'"]);

    // Reset returns to the sheet's own key — still re-fingered for the flute.
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByText("Flute D · tonic M")).toBeInTheDocument();
  });

  it("asks what you are playing once per playing session, and applies the answer", async () => {
    sessionStorage.clear(); // a fresh playing session: the app was just opened
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container, unmount } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("What are you playing?");

    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Instrument"), {
      target: { value: "bamboo-flute:2" },
    });
    // The answer applies to the view behind the prompt immediately.
    expect(renderedNotes(container)).toEqual(["D♭,", "N♭,", "S", "G♭", "M", "P", "D♭"]);

    fireEvent.click(screen.getByRole("button", { name: "Start playing" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    unmount();

    // Same playing session, another sheet: asked and answered, so no second nag.
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Flute D · tonic M")).toBeInTheDocument();
  });

  // Finding F37: the nudge is available whenever the view is derived, so its
  // badge cannot be tied to a key change — a flute at the sheet's own key could
  // be shifted two octaves with nothing on screen saying so.
  it("shows the octave nudge on the header even when the key has not changed", async () => {
    localStorage.setItem("saregamapic.instrument", "bamboo-flute:2");
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Concert G");

    // Query the header badge specifically — the nudge BUTTONS also say "8va".
    expect(container.querySelector(".transposed-tag")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /8va▲/ }));
    // The register moved but the key did not, so the badge says so and no more.
    expect(container.querySelector(".transposed-tag")).toHaveTextContent("+1 8va");
    expect(container.querySelector(".transposed-tag")).not.toHaveTextContent("transposed");
  });

  // Finding F35: an unparseable header costs the KEY shift, not the instrument's
  // fingering shift. Handing a flute player alto-sax letters under a picker that
  // says "flute in D" is a silent major 3rd, so the letters must still move.
  it("re-fingers a sheet whose header scale is unknown, and says which flute", async () => {
    localStorage.setItem("saregamapic.instrument", "bamboo-flute:2");
    const noHeader = {
      ...digitalTranscription,
      stf: { ...digitalTranscription.stf, header: { concert_scale: "", alto_scale: "", beat: "" } },
    };
    vi.stubGlobal("fetch", mockFetchJson(detail, noHeader));
    const { container } = renderAt("/songs/abc123/pages/2");
    await screen.findByText("Flute D");

    // Same letters as the concert-G case: the anchor shift never needed the key.
    expect(renderedNotes(container)).toEqual(["D♭,", "N♭,", "S", "G♭", "M", "P", "D♭"]);
    // Only transposing is unavailable, and the view says exactly that.
    expect(screen.queryByLabelText("Key")).not.toBeInTheDocument();
    expect(screen.getByText(/Header scale unknown/)).toBeInTheDocument();
  });

  // Finding F36: React attaches its listeners at the root, so the prompt's own
  // Escape handler does not stop the event reaching the viewer's native window
  // listener — one Escape used to close the prompt AND navigate out.
  it("Escape closes the instrument prompt without leaving the viewer", async () => {
    sessionStorage.clear();
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    renderAt("/songs/abc123/pages/2");
    await screen.findByText("What are you playing?");

    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("Test Sinhala Song — 2 / 2")).toBeInTheDocument();
  });

  it("does not page the sheet behind an open instrument prompt", async () => {
    sessionStorage.clear();
    vi.stubGlobal("fetch", mockFetchJson(detail, digitalTranscription));
    renderAt("/songs/abc123/pages/2");
    await screen.findByText("What are you playing?");

    fireEvent.keyDown(window, { key: "ArrowLeft" });
    expect(screen.getByText("Test Sinhala Song — 2 / 2")).toBeInTheDocument();
  });

  it("does not ask on a page with nothing transcribed to play", async () => {
    sessionStorage.clear();
    vi.stubGlobal("fetch", mockFetchJson(detail)); // no transcription -> 404
    renderAt("/songs/abc123/pages/1");
    await screen.findByText("Test Sinhala Song — 1 / 2");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
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

  it("signs out locally even when the logout request fails (finding F22)", async () => {
    // Offline, or an already-lapsed session: the POST /api/auth/logout rejects.
    // The local sign-out must still happen — the button must not look dead and
    // the runtime caches must be cleared — or a shared/handed-off device keeps
    // the previous user's identity, songs and images readable offline.
    const del = vi.fn().mockResolvedValue(true);
    vi.stubGlobal("caches", { delete: del } as unknown as CacheStorage);
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (url === "/api/auth/me") return Promise.resolve(Response.json(authUser));
        if (url === "/api/auth/logout" && init?.method === "POST") {
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        return Promise.resolve(Response.json(songs));
      }),
    );
    renderAt("/");
    await screen.findByText("Test Sinhala Song");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    // onSignedOut ran despite the rejection → the login screen is shown.
    await screen.findByRole("link", { name: "Continue with Google" });
    // clearOfflineCaches ran too → every runtime cache was dropped.
    expect(del).toHaveBeenCalledTimes(RUNTIME_CACHES.length);
    vi.unstubAllGlobals();
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
