/**
 * Authentication API functions.
 */

import { clearSessionToken, setSessionToken } from "../auth";
import { post } from "./client";

interface LoginResponse {
  session_token: string;
  expires_in: number;
}

/**
 * Login with admin password.
 *
 * Sends credentials to /api/web/auth/login and stores the returned session token.
 *
 * @param password - Admin password
 * @throws ApiError if login fails or response is invalid
 */
export async function login(password: string): Promise<void> {
  const response = await post<LoginResponse>("/api/web/auth/login", {
    password,
  });

  if (!response.session_token) {
    throw new Error("Login response missing session token");
  }

  setSessionToken(response.session_token);
}

/**
 * Logout and invalidate current session token.
 *
 * Clears local session regardless of backend response.
 */
export async function logout(): Promise<void> {
  try {
    await post("/api/web/auth/logout");
  } catch (error) {
    // Don't throw - just log. The important part is clearing local session.
    console.warn("[Auth] Logout request failed:", error);
  } finally {
    clearSessionToken();
  }
}
