import { beforeEach, describe, expect, it, vi } from "vitest";

import { clearSessionToken, setSessionToken } from "../auth";

import { login, logout } from "./auth";
import { ApiError, post } from "./client";

vi.mock("./client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./client")>();
  return {
    ...actual,
    post: vi.fn(),
  };
});

vi.mock("../auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../auth")>();
  return {
    ...actual,
    setSessionToken: vi.fn(),
    clearSessionToken: vi.fn(),
  };
});

describe("login", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts the password and stores the returned session token", async () => {
    const response = { session_token: "tok-123", expires_in: 86400 };
    vi.mocked(post).mockResolvedValue(response);

    await expect(login("admin-pw")).resolves.toBeUndefined();

    expect(post).toHaveBeenCalledWith("/api/web/authentication/login", {
      password: "admin-pw",
    });
    expect(setSessionToken).toHaveBeenCalledWith("tok-123");
  });

  it("rejects and does not store a token when session_token is missing", async () => {
    vi.mocked(post).mockResolvedValue({ session_token: "", expires_in: 86400 });

    await expect(login("admin-pw")).rejects.toThrow(
      "Login response missing session token"
    );
    expect(setSessionToken).not.toHaveBeenCalled();
  });

  it("lets an ApiError from post bubble up", async () => {
    const error = new ApiError(403, "Invalid password");
    vi.mocked(post).mockRejectedValue(error);

    await expect(login("wrong")).rejects.toBe(error);
    expect(setSessionToken).not.toHaveBeenCalled();
  });
});

describe("logout", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("posts to the logout endpoint and clears the session token on success", async () => {
    vi.mocked(post).mockResolvedValue({ status: "logged_out" });

    await expect(logout()).resolves.toBeUndefined();

    expect(post).toHaveBeenCalledWith("/api/web/authentication/logout");
    expect(clearSessionToken).toHaveBeenCalled();
  });

  it("clears the session token and does not throw when the backend call fails", async () => {
    const error = new ApiError(500, "Server error");
    vi.mocked(post).mockRejectedValue(error);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(logout()).resolves.toBeUndefined();

    expect(post).toHaveBeenCalledWith("/api/web/authentication/logout");
    expect(clearSessionToken).toHaveBeenCalled();
    warnSpy.mockRestore();
  });
});
