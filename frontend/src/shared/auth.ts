/**
 * Authentication utilities.
 *
 * Handles session token storage and authentication state.
 * The backend uses Bearer token authentication via HTTP headers.
 */

const SESSION_KEY = "nomarr_session_token";

/**
 * Get the stored session token.
 *
 * @returns Session token or null if not authenticated
 */
export function getSessionToken(): string | null {
  return localStorage.getItem(SESSION_KEY);
}

/**
 * Store a session token.
 *
 * @param token - Session token from login response
 */
export function setSessionToken(token: string): void {
  localStorage.setItem(SESSION_KEY, token);
}

/**
 * Clear the stored session token (logout).
 */
export function clearSessionToken(): void {
  localStorage.removeItem(SESSION_KEY);
}

/**
 * Logout the user (alias for clearSessionToken).
 */
export function logout(): void {
  clearSessionToken();
}

/**
 * Check if user is authenticated.
 *
 * @returns True if session token exists
 */
export function isAuthenticated(): boolean {
  const token = getSessionToken();
  return !!token && token.length > 0;
}
