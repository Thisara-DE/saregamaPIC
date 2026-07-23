import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { StfLineText, parseNote } from "./components/StfLineText";
import type { SongDetail, Transcription } from "./api/types";

const detail: SongDetail = {
  id: "abc123",
  title: "Test Song",
  notes: "",
  created_at: "2026-07-17T00:00:00Z",
  scan_count: 1,
  cover_scan_id: "scan1",
  scans: [
    {
      id: "scan1",
      song_id: "abc123",
      page_no: 1,
      content_type: "image/jpeg",
      uploaded_at: "2026-07-17T00:00:00Z",
    },
  ],
};

const transcription: Transcription = {
  id: "t1",
  scan_id: "scan1",
  status: "draft",
  stf: {
    header: { concert_scale: "G", alto_scale: "E", beat: "4/4" },
    lines: [{ n: 1, kind: "sargam", text: "S R_ M^ S'" }],
  },
  warnings: [],
  model: "claude-opus-4-8",
  input_tokens: 1200,
  output_tokens: 300,
  updated_at: "2026-07-18T00:00:00Z",
};

/** Route fetch responses by URL + method so the editor's several calls resolve. */
function routeFetch(routes: Record<string, unknown>) {
  return vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const method = init?.method ?? "GET";
    const key = `${method} ${url}`;
    if (key === "GET /api/auth/me") {
      return Promise.resolve(
        Response.json({
          id: "user1",
          email: "thisara@example.com",
          display_name: "Thisara",
        }),
      );
    }
    if (key in routes) {
      const body = routes[key];
      if (body === 404) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "none" }), { status: 404 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.reject(new Error(`unexpected fetch: ${key}`));
  });
}

describe("StfLineText", () => {
  it("parses accidentals and octave dots from a token", () => {
    expect(parseNote("R_")).toMatchObject({ letter: "R", flat: true, sharp: false });
    expect(parseNote("M^")).toMatchObject({ letter: "M", sharp: true, flat: false });
    expect(parseNote("S'")).toMatchObject({ letter: "S", above: 1, below: 0 });
    expect(parseNote("R_,")).toMatchObject({ letter: "R", flat: true, below: 1 });
  });

  it("renders flat and sharp marks as styled notes", () => {
    const { container } = render(<StfLineText text="R_ M^" />);
    expect(container.querySelector(".stf-note.flat")).not.toBeNull();
    expect(container.querySelector(".stf-note.sharp")).not.toBeNull();
  });

  it("renders a curve group as an arc, not literal parens", () => {
    const { container } = render(<StfLineText text="G (SRGM) P" />);
    const curve = container.querySelector(".stf-curve");
    expect(curve).not.toBeNull();
    expect(curve?.querySelectorAll(".stf-note")).toHaveLength(4); // S R G M inside
    expect(container.textContent).not.toContain("("); // parens dropped, arc drawn
    expect(container.textContent).not.toContain(")");
  });

  it("leaves an unclosed curve paren as literal text (mid-typing)", () => {
    const { container } = render(<StfLineText text="G (SR" />);
    expect(container.querySelector(".stf-curve")).toBeNull();
    expect(container.textContent).toContain("(");
  });
});

describe("EditorPage", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("loads an existing draft and renders its lines", async () => {
    vi.stubGlobal(
      "fetch",
      routeFetch({
        "GET /api/songs/abc123": detail,
        "GET /api/scans/scan1/transcription": transcription,
      }),
    );
    render(
      <MemoryRouter initialEntries={["/songs/abc123/pages/1/edit"]}>
        <App />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(screen.getByDisplayValue("S R_ M^ S'")).toBeInTheDocument();
    });
    // draft status pill + a Re-recognize action (transcription already exists)
    expect(screen.getByText("draft")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-recognize" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Page 1 of/ })).toHaveAttribute(
      "src",
      "/api/scans/scan1/preview",
    );
  });

  it("offers Recognize when no transcription exists yet", async () => {
    vi.stubGlobal(
      "fetch",
      routeFetch({
        "GET /api/songs/abc123": detail,
        "GET /api/scans/scan1/transcription": 404,
      }),
    );
    render(
      <MemoryRouter initialEntries={["/songs/abc123/pages/1/edit"]}>
        <App />
      </MemoryRouter>,
    );
    await waitFor(() => {
      expect(
        screen.getByText((content) => content.startsWith("No transcription yet")),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Recognize" })).toBeInTheDocument();
  });
});
