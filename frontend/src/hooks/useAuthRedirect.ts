/**
 * Hook for handling authentication redirects.
 * 
 * Provides a global way to redirect to login when auth fails.
 */

import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

// Global redirect function storage
let globalRedirectToLogin: (() => void) | null = null;

/**
 * Set the global redirect function.
 * Called by useAuthRedirect hook to register the navigate function.
 */
export function setGlobalAuthRedirect(redirectFn: () => void): void {
  globalRedirectToLogin = redirectFn;
}

/**
 * Trigger a redirect to login from anywhere in the app.
 * Used by API client when 401/403 is received.
 */
export function redirectToLogin(): void {
  if (globalRedirectToLogin) {
    globalRedirectToLogin();
  } else {
    // Fallback - reload page which will trigger auth check
    window.location.reload();
  }
}

/**
 * Hook to register auth redirect capability.
 * Should be used once at the app level.
 */
export function useAuthRedirect(): void {
  const navigate = useNavigate();

  useEffect(() => {
    // Register the redirect function
    setGlobalAuthRedirect(() => {
      navigate("/login", { replace: true });
    });

    // Cleanup on unmount
    return () => {
      globalRedirectToLogin = null;
    };
  }, [navigate]);
}