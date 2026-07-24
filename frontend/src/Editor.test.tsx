import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { StfLineText, parseNote } from "./components/StfLineText";
import { recognizeScan } from "./api/client";
import type { SongDetail, Transcription } from "./api/types";

const detail: SongDetail = {
  id: "abc123",
  title: "Test Song",
  notes: "",
  created_at: "2026-07-17T00:00:00Z",
  scan_count: 1,
  cover_scan_id: "scan1",
  digital_page_no: 1,
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

describe("recognition network recovery", () => {
  it("reuses the idempotency key and returns the completed draft after a dropped connection", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(transcription), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const onRecovering = vi.fn();

    await expect(recognizeScan("scan1", onRecovering)).resolves.toEqual(transcription);

    expect(onRecovering).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstHeaders = fetchMock.mock.calls[0]![1]?.headers as Record<string, string>;
    const secondHeaders = fetchMock.mock.calls[1]![1]?.headers as Record<string, string>;
    expect(secondHeaders["Idempotency-Key"]).toBe(firstHeaders["Idempotency-Key"]);
  });

  it("polls the same action when the backend is still finishing it", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            detail: "Recognition with this Idempotency-Key is in progress",
          }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(transcription), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = recognizeScan("scan1");
    await vi.runAllTimersAsync();
    await expect(result).resolves.toEqual(transcription);

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const keys = fetchMock.mock.calls.map(
      (call) => (call[1]?.headers as Record<string, string>)["Idempotency-Key"],
    );
    expect(new Set(keys).size).toBe(1);
    vi.useRealTimers();
  });

  it("starts the recovery budget at the interruption, not at the start of the call", async () => {
    // The budget used to be measured from the start of the call, so a slow
    // recognition — the exact case recovery exists for — arrived at its first
    // retry with nothing left and gave up without polling once.
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(async () => {
        vi.advanceTimersByTime(300_000); // recognition ran well past the old budget
        throw new TypeError("Failed to fetch");
      })
      .mockResolvedValueOnce(
        new Response(JSON.stringify(transcription), {
          status: 201,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = recognizeScan("scan1");
    await vi.runAllTimersAsync();
    await expect(result).resolves.toEqual(transcription);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("says recognition is still running rather than leaking the idempotency error", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn().mockImplementation(
      async () =>
        new Response(
          JSON.stringify({ detail: "Recognition with this Idempotency-Key is in progress" }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = recognizeScan("scan1");
    const assertion = expect(result).rejects.toThrow(/still running/i);
    await vi.runAllTimersAsync();
    await assertion;
    await expect(result.catch((e: Error) => e.message)).resolves.not.toMatch(/Idempotency-Key/);
    vi.useRealTimers();
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

describe("EditorPage title editing", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renames the song on blur when the title changed, and skips the call when it didn't", async () => {
    const untitled = { ...detail, title: "" };
    const renamed = { id: "abc123", title: "Sudu Nelum", notes: "", created_at: detail.created_at };
    const fetchMock = routeFetch({
      "GET /api/songs/abc123": untitled,
      "GET /api/scans/scan1/transcription": transcription,
      "PATCH /api/songs/abc123": renamed,
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={["/songs/abc123/pages/1/edit"]}>
        <App />
      </MemoryRouter>,
    );
    const titleInput = await screen.findByRole("textbox", { name: "Song title" });

    // Blur without editing: no rename request fires.
    fireEvent.blur(titleInput);
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === "PATCH")).toBe(
      false,
    );

    // Type a name and blur: exactly one PATCH carrying the new title.
    fireEvent.change(titleInput, { target: { value: "Sudu Nelum" } });
    fireEvent.blur(titleInput);
    await waitFor(() => {
      const patch = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "PATCH");
      expect(patch).toBeTruthy();
      expect(JSON.parse((patch![1] as RequestInit).body as string)).toEqual({ title: "Sudu Nelum" });
    });
  });
});

describe("EditorPage save confirmation", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("offers the digital version right after a save, and drops it once editing resumes", async () => {
    // The editor shows one line at a time, so whether the sheet ALIGNS is only
    // visible in the digital view. Without this the reader has to walk back out
    // to the song page and toggle to see the thing they just corrected.
    const reviewed = { ...transcription, status: "reviewed" as const };
    vi.stubGlobal(
      "fetch",
      routeFetch({
        "GET /api/songs/abc123": detail,
        "GET /api/scans/scan1/transcription": transcription,
        "PUT /api/scans/scan1/transcription": reviewed,
      }),
    );
    render(
      <MemoryRouter initialEntries={["/songs/abc123/pages/1/edit"]}>
        <App />
      </MemoryRouter>,
    );
    await screen.findByDisplayValue("S R_ M^ S'");
    expect(screen.queryByRole("button", { name: /digital version/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Mark reviewed" }));

    expect(await screen.findByText("Marked reviewed.")).toBeInTheDocument();
    const toDigital = screen.getByRole("button", { name: /See the digital version/ });
    fireEvent.click(toDigital);
    // Straight to the viewer for this page, which now opens on the digital view.
    await screen.findByText((text) => text.includes("— 1 /"));
  });

  it("clears the save confirmation as soon as a line changes", async () => {
    const reviewed = { ...transcription, status: "reviewed" as const };
    vi.stubGlobal(
      "fetch",
      routeFetch({
        "GET /api/songs/abc123": detail,
        "GET /api/scans/scan1/transcription": transcription,
        "PUT /api/scans/scan1/transcription": reviewed,
      }),
    );
    render(
      <MemoryRouter initialEntries={["/songs/abc123/pages/1/edit"]}>
        <App />
      </MemoryRouter>,
    );
    const line = await screen.findByDisplayValue("S R_ M^ S'");
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByText("Draft saved.")).toBeInTheDocument();

    // A stale "saved" banner over unsaved edits would be a lie.
    fireEvent.change(line, { target: { value: "S R_ M^ S' G" } });
    await waitFor(() => {
      expect(screen.queryByText("Draft saved.")).not.toBeInTheDocument();
    });
  });
});
