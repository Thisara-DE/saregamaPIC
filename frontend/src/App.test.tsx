import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { Song } from "./api/types";

const songs: Song[] = [
  {
    id: "abc123",
    title: "Test Sinhala Song",
    notes: "",
    created_at: "2026-07-17T00:00:00Z",
    scan_count: 2,
  },
];

function mockFetchJson(body: unknown) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

describe("App", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("lists songs from the API", async () => {
    vi.stubGlobal("fetch", mockFetchJson(songs));
    render(<App />);
    expect(screen.getByText("SaReGaMaPic")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText("Test Sinhala Song")).toBeInTheDocument();
    });
    expect(screen.getByText("2 pages")).toBeInTheDocument();
  });

  it("shows API errors instead of crashing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
      ),
    );
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
  });
});
