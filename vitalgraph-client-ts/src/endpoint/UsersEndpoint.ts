import { BaseEndpoint } from './BaseEndpoint.js';
import { validateRequired } from '../utils/params.js';
import type {
  UserResponse,
  UsersListResponse,
  UserCreateResponse,
  UserUpdateResponse,
  UserDeleteResponse,
  PasswordChangeResponse,
  VitalGraphResponse,
} from '../response/types.js';

export class UsersEndpoint extends BaseEndpoint {
  async list(): Promise<UsersListResponse> {
    return this.request('GET', '/api/users');
  }

  async get(userId: string): Promise<UserResponse> {
    validateRequired({ user_id: userId });
    return this.request('GET', '/api/users/user', { params: { user_id: userId } });
  }

  async create(data: Record<string, unknown>): Promise<UserCreateResponse> {
    return this.request('POST', '/api/users', { json: data });
  }

  async update(userId: string, data: Record<string, unknown>): Promise<UserUpdateResponse> {
    validateRequired({ user_id: userId });
    return this.request('PUT', '/api/users', { params: { user_id: userId }, json: data });
  }

  async delete(userId: string): Promise<UserDeleteResponse> {
    validateRequired({ user_id: userId });
    return this.request('DELETE', '/api/users', { params: { user_id: userId } });
  }

  async getSpaceAccess(userId: string): Promise<VitalGraphResponse> {
    validateRequired({ user_id: userId });
    return this.request('GET', '/api/users/spaces', { params: { user_id: userId } });
  }

  async grantSpaceAccess(userId: string, spaceId: string, data?: Record<string, unknown>): Promise<VitalGraphResponse> {
    validateRequired({ user_id: userId, space_id: spaceId });
    return this.request('PUT', '/api/users/spaces', {
      params: { user_id: userId, space_id: spaceId },
      json: data,
    });
  }

  async revokeSpaceAccess(userId: string, spaceId: string): Promise<VitalGraphResponse> {
    validateRequired({ user_id: userId, space_id: spaceId });
    return this.request('DELETE', '/api/users/spaces', {
      params: { user_id: userId, space_id: spaceId },
    });
  }

  async changePassword(currentPassword: string, newPassword: string): Promise<PasswordChangeResponse> {
    return this.request('POST', '/api/users/me/password', {
      json: { current_password: currentPassword, new_password: newPassword },
    });
  }
}
