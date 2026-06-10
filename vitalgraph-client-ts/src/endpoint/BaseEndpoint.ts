import type { VitalGraphClient } from '../VitalGraphClient.js';
import type { VitalGraphResponse } from '../response/types.js';
import { VitalGraphClientError } from '../utils/errors.js';
import { buildQueryParams } from '../utils/params.js';

export interface RequestOptions {
  params?: Record<string, unknown>;
  json?: unknown;
  body?: BodyInit;
  headers?: Record<string, string>;
}

export abstract class BaseEndpoint {
  constructor(protected client: VitalGraphClient) {}

  protected get serverUrl(): string {
    return this.client.config.serverUrl;
  }

  protected checkConnection(): void {
    if (!this.client.isConnected()) {
      throw new VitalGraphClientError('Client is not connected');
    }
  }

  /**
   * Make an authenticated request and return the parsed JSON response.
   */
  protected async request<T extends VitalGraphResponse>(
    method: string,
    path: string,
    options?: RequestOptions,
  ): Promise<T> {
    this.checkConnection();

    let url = `${this.serverUrl}${path}`;

    if (options?.params) {
      const qs = buildQueryParams(options.params);
      const qsStr = qs.toString();
      if (qsStr) url += `?${qsStr}`;
    }

    const fetchOptions: RequestInit = {
      method,
      headers: { ...options?.headers },
    };

    if (options?.json !== undefined) {
      (fetchOptions.headers as Record<string, string>)['Content-Type'] = 'application/json';
      fetchOptions.body = JSON.stringify(options.json);
    } else if (options?.body !== undefined) {
      fetchOptions.body = options.body;
    }

    const response = await this.client.makeAuthenticatedRequest(url, fetchOptions);
    const data = await response.json();
    return data as T;
  }

  /**
   * Make an authenticated request and return the raw Response (for binary downloads).
   */
  protected async requestRaw(
    method: string,
    path: string,
    options?: RequestOptions,
  ): Promise<Response> {
    this.checkConnection();

    let url = `${this.serverUrl}${path}`;

    if (options?.params) {
      const qs = buildQueryParams(options.params);
      const qsStr = qs.toString();
      if (qsStr) url += `?${qsStr}`;
    }

    const fetchOptions: RequestInit = {
      method,
      headers: { ...options?.headers },
    };

    return this.client.makeAuthenticatedRequest(url, fetchOptions);
  }
}
