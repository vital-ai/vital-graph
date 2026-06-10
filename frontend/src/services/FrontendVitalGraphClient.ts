/**
 * Browser-adapted VitalGraphClient.
 *
 * Bridges the published @vital-ai/vitalgraph-client with the frontend's
 * existing AuthService (localStorage tokens, refresh, redirect-on-401).
 *
 * All endpoint instances (spaces, graphs, kgentities, …) are inherited from
 * VitalGraphClient and work unchanged — only the underlying fetch call is
 * replaced to use the frontend auth layer.
 */

import { VitalGraphClient } from '@vital-ai/vitalgraph-client';
import { authService } from './AuthService';

/**
 * Subclass that:
 *  1. Reports itself as always-connected (the AuthService owns session state).
 *  2. Overrides makeAuthenticatedRequest to inject the AuthService token
 *     and delegate 401 handling to AuthService.
 */
class FrontendVitalGraphClient extends VitalGraphClient {
  constructor() {
    // serverUrl = current origin so endpoint paths resolve correctly
    super({ serverUrl: window.location.origin });
  }

  /* ------------------------------------------------------------------ */
  /* Override connection check — the AuthService decides connectivity    */
  /* ------------------------------------------------------------------ */

  override isConnected(): boolean {
    return true; // endpoint reachability is gated by AuthService
  }

  /* ------------------------------------------------------------------ */
  /* Override fetch to use AuthService tokens + 401 handling             */
  /* ------------------------------------------------------------------ */

  /**
   * Raw authenticated fetch — injects token, handles 401 refresh,
   * but does NOT throw on non-OK responses (returns the Response as-is).
   */
  async makeRawAuthenticatedRequest(
    url: string,
    init: RequestInit,
  ): Promise<Response> {
    const headers = new Headers(init.headers);

    // Inject current bearer token
    const authHeader = authService.getAuthHeader();
    if ('Authorization' in authHeader) {
      headers.set('Authorization', (authHeader as { Authorization: string }).Authorization);
    }
    headers.set('Accept', 'application/json');

    let response = await fetch(url, { ...init, headers });

    // Reactive 401 handling
    if (response.status === 401) {
      const refreshed = await authService.refreshAccessToken();
      if (refreshed) {
        const newAuth = authService.getAuthHeader();
        if ('Authorization' in newAuth) {
          headers.set('Authorization', (newAuth as { Authorization: string }).Authorization);
        }
        response = await fetch(url, { ...init, headers });
      } else {
        // Refresh failed → redirect to login
        window.location.href = '/login';
      }
    }

    return response;
  }

  /**
   * Authenticated fetch that throws on non-OK responses.
   * Used by BaseEndpoint.request() so typed endpoint methods propagate errors.
   */
  override async makeAuthenticatedRequest(
    url: string,
    init: RequestInit,
  ): Promise<Response> {
    const response = await this.makeRawAuthenticatedRequest(url, init);

    if (!response.ok) {
      const body = await response.text().catch(() => '');
      throw new Error(
        `Request failed: ${response.status} ${response.statusText} — ${body}`,
      );
    }

    return response;
  }
}

/** Singleton instance shared across the frontend. */
export const vgClient = new FrontendVitalGraphClient();
export default vgClient;
