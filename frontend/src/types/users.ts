/**
 * User types for VitalGraph frontend
 */

export type UserRole = 'admin' | 'user' | 'reader';

export interface User {
  id: string;
  username: string;
  full_name?: string;
  email?: string;
  role: UserRole;
  is_active: boolean;
  spaces?: Record<string, string>;
  token_version?: number;
  created_time?: string;
  last_login?: string;
  profile_image?: string;
}

export interface CreateUserRequest {
  username: string;
  password: string;
  role?: UserRole;
  email?: string;
  full_name?: string;
}

export interface UpdateUserRequest {
  role?: UserRole;
  email?: string;
  full_name?: string;
  is_active?: boolean;
  spaces?: Record<string, string>;
}
