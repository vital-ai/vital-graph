import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  ApiKeyInfo,
  ApiKeyListResponse,
  ApiKeyCreateResponse,
  ApiKeyDeleteResponse,
} from '../response/types.js';

export class ApiKeysEndpoint extends BaseEndpoint {
  async list(username?: string): Promise<ApiKeyListResponse> {
    return this.request('GET', '/api/keys', { params: username ? { username } : undefined });
  }

  async get(keyId: string): Promise<ApiKeyInfo> {
    validateRequired({ key_id: keyId });
    return this.request('GET', '/api/keys/key', { params: { key_id: keyId } });
  }

  async create(name: string, data?: Record<string, unknown>): Promise<ApiKeyCreateResponse> {
    return this.request('POST', '/api/keys', { json: { name, ...data } });
  }

  async delete(keyId: string): Promise<ApiKeyDeleteResponse> {
    validateRequired({ key_id: keyId });
    return this.request('DELETE', '/api/keys', { params: { key_id: keyId } });
  }
}
