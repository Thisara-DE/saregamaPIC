import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearOfflineCaches, invalidateCached, useOnlineStatus } from "./offline";
import { API_CACHE, RUNTIME_CACHES } from "./swCache";

describe("useOnlineStatus", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts from navigator.onLine", () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    const { result } = renderHook(() => useOnlineStatus());
    expect(result.current).toBe(false);
  });

  it("flips to offline on the offline event and back on online", () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
    const { result } = renderHook(() => useOnlineStatus());
    expect(result.current).toBe(true);

    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(result.current).toBe(false);

    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(result.current).toBe(true);
  });

  it("removes its listeners on unmount", () => {
    const remove = vi.spyOn(window, "removeEventListener");
    const { unmount } = renderHook(() => useOnlineStatus());
    unmount();
    expect(remove).toHaveBeenCalledWith("online", expect.any(Function));
    expect(remove).toHaveBeenCalledWith("offline", expect.any(Function));
  });
});

describe("clearOfflineCaches", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("deletes exactly the app's runtime caches, not the precache", async () => {
    const del = vi.fn().mockResolvedValue(true);
    vi.stubGlobal("caches", { delete: del } as unknown as CacheStorage);

    await clearOfflineCaches();

    expect(del).toHaveBeenCalledTimes(RUNTIME_CACHES.length);
    for (const name of RUNTIME_CACHES) {
      expect(del).toHaveBeenCalledWith(name);
    }
  });

  it("is a no-op (does not throw) where Cache Storage is absent", async () => {
    vi.stubGlobal("caches", undefined);
    await expect(clearOfflineCaches()).resolves.toBeUndefined();
  });
});

describe("invalidateCached (finding F21)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("deletes exactly the given paths from the read-data cache", async () => {
    const del = vi.fn().mockResolvedValue(true);
    const open = vi.fn().mockResolvedValue({ delete: del } as unknown as Cache);
    vi.stubGlobal("caches", { open } as unknown as CacheStorage);

    await invalidateCached(["/api/scans/s1/transcription", "/api/songs"]);

    // Only the read-data cache is touched — never the identity or image caches.
    expect(open).toHaveBeenCalledTimes(1);
    expect(open).toHaveBeenCalledWith(API_CACHE);
    expect(del).toHaveBeenCalledWith("/api/scans/s1/transcription");
    expect(del).toHaveBeenCalledWith("/api/songs");
    expect(del).toHaveBeenCalledTimes(2);
  });

  it("is a no-op (does not throw) where Cache Storage is absent", async () => {
    vi.stubGlobal("caches", undefined);
    await expect(invalidateCached(["/api/songs"])).resolves.toBeUndefined();
  });

  it("swallows a cache error so a failed eviction never fails the write it follows", async () => {
    const open = vi.fn().mockRejectedValue(new Error("cache unavailable"));
    vi.stubGlobal("caches", { open } as unknown as CacheStorage);
    await expect(invalidateCached(["/api/songs"])).resolves.toBeUndefined();
  });
});
