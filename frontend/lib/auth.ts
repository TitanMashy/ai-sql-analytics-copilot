const STORAGE_KEY = "analytics.accessToken";

/**
 * The bearer token for the analytics API.
 *
 * It lives in sessionStorage, so it is scoped to the tab and disappears when the tab closes. The
 * token is issued by the deployment's identity provider (or `scripts/issue_token.py` for local
 * JWT testing); this app only stores and forwards it. Storage access can throw in private
 * windows or when site data is blocked, so every call degrades to "no token".
 */
export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, token.trim());
  } catch {
    // Without storage the token cannot be kept; the user will be asked again on the next 401.
  }
}

export function clearAuthToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}
