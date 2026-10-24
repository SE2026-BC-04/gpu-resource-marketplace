import { AuthApiError } from "./auth";
import type { AuthApi, AuthUser } from "./auth";

export type SignedOutReason = "signed-out" | "expired" | "unauthorized";

export type SessionState =
  | { status: "signed-out"; reason?: SignedOutReason }
  | { status: "signed-in"; user: AuthUser };

export interface SessionStore {
  getState(): SessionState;
  subscribe(listener: () => void): () => void;
  /** Current bearer token for API clients (Listings, Jobs); null when signed out. */
  getAccessToken(): string | null;
  signIn(loginName: string, password: string, signal?: AbortSignal): Promise<AuthUser>;
  /** Forgets the token locally first, then tells the API; the issued JWT is not revoked (section 4.4). */
  signOut(): Promise<void>;
  /** For API clients that receive 401 for the current token. */
  handleUnauthorized(): void;
}

interface Timers {
  setTimeout(callback: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

const browserTimers: Timers = {
  setTimeout: (callback, ms) => globalThis.setTimeout(callback, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/**
 * Session held only in this JavaScript closure (P1C-AC-07): never written to Web Storage,
 * IndexedDB, cookies or the URL, so a page reload always starts signed out.
 */
export function createSessionStore(api: AuthApi, timers: Timers = browserTimers): SessionStore {
  let state: SessionState = { status: "signed-out" };
  let token: string | null = null;
  let expiry: unknown = null;
  // Bumped on every sign-in/sign-out so a slow, older request cannot restore a session.
  let generation = 0;
  const listeners = new Set<() => void>();

  function publish(next: SessionState): void {
    state = next;
    listeners.forEach((listener) => listener());
  }

  function clear(reason: SignedOutReason): void {
    generation += 1;
    token = null;
    if (expiry !== null) timers.clearTimeout(expiry);
    expiry = null;
    publish({ status: "signed-out", reason });
  }

  return {
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getAccessToken: () => token,

    async signIn(loginName, password, signal) {
      if (token !== null) clear("signed-out");
      const attempt = ++generation;
      const result = await api.login(loginName, password, signal);
      // Confirm the identity from the database before showing it (Phase 1C section 2.6).
      const current = await api.me(result.accessToken, signal);
      if (attempt !== generation) throw new DOMException("Sign-in superseded", "AbortError");
      if (current.id !== result.user.id) throw new AuthApiError("INVALID_RESPONSE", 502);
      token = result.accessToken;
      // The server rejects the token at exp anyway; this only returns the UI to Login on time.
      expiry = timers.setTimeout(() => clear("expired"), result.expiresInSeconds * 1000);
      publish({ status: "signed-in", user: current });
      return current;
    },

    async signOut() {
      const issued = token;
      clear("signed-out");
      if (issued === null) return;
      try {
        await api.logout(issued);
      } catch {
        // Already forgotten locally; a failed call cannot keep the session alive.
      }
    },

    handleUnauthorized() {
      if (token !== null) clear("unauthorized");
    },
  };
}
