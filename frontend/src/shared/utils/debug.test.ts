import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

import { isDebug, debugLog } from "./debug";

// In jsdom, `localStorage` may not be available on the global scope by default.
// We stub it manually to ensure reliable test behavior.
const store: Record<string, string> = {};

function mockLocalStorage() {
  vi.stubGlobal(
    "localStorage",
    {
      getItem: vi.fn((key: string) => store[key] ?? null),
      setItem: vi.fn((key: string, value: string) => {
        store[key] = value;
      }),
      removeItem: vi.fn((key: string) => {
        delete store[key];
      }),
      clear: vi.fn(() => {
        Object.keys(store).forEach((key) => delete store[key]);
      }),
    },
  );
}

describe("isDebug", () => {
  beforeEach(() => {
    mockLocalStorage();
    Object.keys(store).forEach((key) => delete store[key]);
  });

  it("returns false when localStorage key is not set", () => {
    expect(isDebug()).toBe(false);
  });

  it("returns true when localStorage key is set to 'true'", () => {
    store["nomarr_debug"] = "true";
    expect(isDebug()).toBe(true);
  });

  it("returns false when localStorage key is set to any other value", () => {
    store["nomarr_debug"] = "false";
    expect(isDebug()).toBe(false);
  });

  it("returns false when localStorage is unavailable (e.g., throws)", () => {
    vi.stubGlobal(
      "localStorage",
      {
        getItem: () => {
          throw new Error("storage unavailable");
        },
      },
    );
    expect(isDebug()).toBe(false);
  });
});

describe("debugLog", () => {
  beforeEach(() => {
    mockLocalStorage();
    Object.keys(store).forEach((key) => delete store[key]);
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("logs with tag and message when debug is on", () => {
    store["nomarr_debug"] = "true";
    const spy = vi.spyOn(console, "debug").mockImplementation(() => {});

    debugLog("TestTag", "test event");

    expect(spy).toHaveBeenCalledWith("[nomarr:TestTag]", "test event");
  });

  it("logs with tag, message, and data when debug is on", () => {
    store["nomarr_debug"] = "true";
    const spy = vi.spyOn(console, "debug").mockImplementation(() => {});

    debugLog("TestTag", "test event", { id: 42 });

    expect(spy).toHaveBeenCalledWith("[nomarr:TestTag]", "test event", { id: 42 });
  });

  it("does not log when debug is off", () => {
    const spy = vi.spyOn(console, "debug").mockImplementation(() => {});

    debugLog("TestTag", "test event");

    expect(spy).not.toHaveBeenCalled();
  });
});
