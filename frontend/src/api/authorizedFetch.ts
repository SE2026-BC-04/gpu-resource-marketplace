import { config } from "../config";
import { AuthApiError, isAbortError } from "./auth";
import type { SessionStore } from "./session";

/** fetch for protected routes: `path` is relative to the API base URL, e.g. "/api/v1/gpu-listings". */
export type AuthorizedFetch = (path: string, init?: RequestInit) => Promise<Response>;

/**
 * Shared Bearer client for GPU-004/GPU-005 (Phase 1C section 2.6). It reads the token at send
 * time, never sends cookies, and on 401 ends the session only if that same token is still current.
 */
export function createAuthorizedFetch(session: SessionStore, fetcher: typeof fetch = fetch): AuthorizedFetch {
  return async (path, init = {}) => {
    if (!path.startsWith("/")) throw new TypeError("path must start with /");
    const sent = session.getAccessToken();
    if (sent === null) throw new AuthApiError("UNAUTHORIZED", 401);
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${sent}`);
    let response: Response;
    try {
      response = await fetcher(`${config.apiBaseUrl}${path}`, {
        cache: "no-store", ...init, headers, credentials: "omit",
      });
    } catch (error) {
      if (init.signal?.aborted || isAbortError(error)) throw error;
      throw new AuthApiError("NETWORK_ERROR", 0);
    }
    if (response.status === 401) session.handleUnauthorized(sent);
    return response;
  };
}
