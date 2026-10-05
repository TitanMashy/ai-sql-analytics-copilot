import { afterEach, describe, expect, it, vi } from "vitest";

import { clearAuthToken, getAuthToken, setAuthToken } from "@/lib/auth";

describe("auth token storage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it("stores a trimmed token for the current tab only", () => {
    setAuthToken("  abc  ");

    expect(getAuthToken()).toBe("abc");
    expect(window.localStorage.getItem("analytics.accessToken")).toBeNull();
  });

  it("clears the token", () => {
    setAuthToken("abc");
    clearAuthToken();

    expect(getAuthToken()).toBeNull();
  });

  it("degrades to no token when storage is unavailable", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });

    expect(getAuthToken()).toBeNull();
    expect(() => setAuthToken("abc")).not.toThrow();
  });
});
