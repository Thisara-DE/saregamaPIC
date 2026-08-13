import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearOfflineCaches, useOnlineStatus } from "./offline";
import { RUNTIME_CACHES } from "./swCache";

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
