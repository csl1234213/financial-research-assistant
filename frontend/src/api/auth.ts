import { getJson, postJson } from './client';
import {
  parseAuthUser,
  parseLoginResponse,
  parseRegisterResponse,
} from './authContract';
import { clearAccessToken, setAccessToken } from './session';
import type { AuthUser } from '../types/auth';

export async function getCurrentUser(): Promise<AuthUser> {
  return parseAuthUser(await getJson('/v1/auth/me'));
}

export async function registerUser(
  email: string,
  password: string,
): Promise<AuthUser> {
  const response = parseRegisterResponse(await postJson('/v1/auth/register', {
    email,
    password,
  }));
  setAccessToken(response.token);

  try {
    return await getCurrentUser();
  } catch (error) {
    clearAccessToken();
    throw error;
  }
}

export async function loginUser(
  email: string,
  password: string,
): Promise<AuthUser> {
  const response = parseLoginResponse(await postJson('/v1/auth/login', {
    email,
    password,
  }));
  setAccessToken(response.access_token);

  try {
    return await getCurrentUser();
  } catch (error) {
    clearAccessToken();
    throw error;
  }
}

export function logoutUser(): void {
  clearAccessToken();
}
