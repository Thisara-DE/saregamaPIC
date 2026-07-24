import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "./App";
import { StfLineText, parseNote } from "./components/StfLineText";
import { recognizeScan } from "./api/client";
import type { SongDetail, Transcription } from "./api/types";

/** Render the app at a route through the real (data-router) route tree. */
function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

const detail: SongDetail = {
  id: "abc123",
  title: "Test Song",
  notes: "",
  created_at: "2026-07-17T00:00:00Z",
  scan_count: 1,
  cover_scan_id: "scan1",
  digital_page_no: 1,
  status: "draft",
  scans: [
    {
      id: "scan1",
      song_id: "abc123",
      page_no: 1,
      content_type: "image/jpeg",
      uploaded_at: "2026-07-17T00:00:00Z",
      status: "draft",
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
    renderAt("/songs/abc123/pages/1/edit");
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
    renderAt("/songs/abc123/pages/1/edit");
    await waitFor(() => {
      expect(
        screen.getByText((content) => content.startsWith("No transcription yet")),
      ).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Recognize" })).toBeInTheDocument();
  });

  it("inserts a blank line right below the one whose + you click, not at the bottom", async () => {
    const twoLines: Transcription = {
      ...transcription,
      stf: {
        header: transcription.stf.header,
        lines: [
          { n: 1, kind: "sargam", text: "AAA" },
          { n: 2, kind: "sargam", text: "BBB" },
        ],
      },
    };
    vi.stubGlobal(
      "fetch",
      routeFetch({
        "GET /api/songs/abc123": detail,
        "GET /api/scans/scan1/transcription": twoLines,
      }),
    );
    renderAt("/songs/abc123/pages/1/edit");
    await screen.findByDisplayValue("AAA");

    fireEvent.click(screen.getByRole("button", { name: "Add line after line 1" }));

    // New blank line lands between the two, which renumber; not appended at the end.
    const values = [...document.querySelectorAll<HTMLInputElement>(".stf-line-input")].map(
      (input) => input.value,
    );
    expect(values).toEqual(["AAA", "", "BBB"]);
    // And it takes focus so the reader can type immediately.
    expect(document.activeElement).toBe(screen.getByLabelText("Line 2 text"));
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
    renderAt("/songs/abc123/pages/1/edit");
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
    renderAt("/songs/abc123/pages/1/edit");
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
    renderAt("/songs/abc123/pages/1/edit");
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

describe("EditorPage unsaved-changes guard", () => {
  beforeEach(() => vi.restoreAllMocks());

  function renderEditor(extraRoutes: Record<string, unknown> = {}) {
    const fetchMock = routeFetch({
      "GET /api/songs/abc123": detail,
      "GET /api/scans/scan1/transcription": transcription,
      ...extraRoutes,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderAt("/songs/abc123/pages/1/edit");
    return fetchMock;
  }

  it("leaves immediately when nothing was edited", async () => {
    renderEditor();
    await screen.findByDisplayValue("S R_ M^ S'");

    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));

    // No prompt; the song page (its Photograph action) is shown.
    expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument();
    await screen.findByRole("button", { name: /Photograph sheet/ });
  });

  it("warns on exit with unsaved edits and stays put on Keep editing", async () => {
    renderEditor();
    const line = await screen.findByDisplayValue("S R_ M^ S'");
    fireEvent.change(line, { target: { value: "S R_ M^ S' G" } });

    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    expect(await screen.findByText("Unsaved changes")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Keep editing" }));
    await waitFor(() => expect(screen.queryByText("Unsaved changes")).not.toBeInTheDocument());
    // Still in the editor with the edit intact — no navigation happened.
    expect(screen.getByDisplayValue("S R_ M^ S' G")).toBeInTheDocument();
  });

  it("discards edits and leaves without saving", async () => {
    const fetchMock = renderEditor({ "PUT /api/scans/scan1/transcription": transcription });
    const line = await screen.findByDisplayValue("S R_ M^ S'");
    fireEvent.change(line, { target: { value: "S R_ M^ S' G" } });

    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    fireEvent.click(await screen.findByRole("button", { name: "Discard changes" }));

    await screen.findByRole("button", { name: /Photograph sheet/ });
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === "PUT")).toBe(
      false,
    );
  });

  it("saves then leaves on Save & exit, keeping the current draft status", async () => {
    const fetchMock = renderEditor({ "PUT /api/scans/scan1/transcription": transcription });
    const line = await screen.findByDisplayValue("S R_ M^ S'");
    fireEvent.change(line, { target: { value: "S R_ M^ S' G" } });

    fireEvent.click(screen.getByRole("button", { name: "Close editor" }));
    fireEvent.click(await screen.findByRole("button", { name: "Save & exit" }));

    await screen.findByRole("button", { name: /Photograph sheet/ });
    const put = fetchMock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "PUT");
    expect(put).toBeTruthy();
    const body = JSON.parse((put![1] as RequestInit).body as string);
    expect(body.status).toBe("draft");
    expect(body.stf.lines[0].text).toBe("S R_ M^ S' G");
  });

  it("guards the browser Back button, not only the ✕", async () => {
    vi.stubGlobal(
      "fetch",
      routeFetch({
        "GET /api/songs/abc123": detail,
        "GET /api/scans/scan1/transcription": transcription,
      }),
    );
    // Start with the song page already in history, then the editor on top, so a
    // Back press has somewhere to pop to.
    const router = createMemoryRouter(routes, {
      initialEntries: ["/songs/abc123", "/songs/abc123/pages/1/edit"],
      initialIndex: 1,
    });
    render(<RouterProvider router={router} />);

    const line = await screen.findByDisplayValue("S R_ M^ S'");
    fireEvent.change(line, { target: { value: "S R_ M^ S' G" } });

    // Simulate the browser Back button — a POP navigation, not the ✕.
    await act(async () => {
      await router.navigate(-1);
    });
    expect(await screen.findByText("Unsaved changes")).toBeInTheDocument();

    // Discarding lets the back navigation through to the song page.
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    await screen.findByRole("button", { name: /Photograph sheet/ });
  });
});
