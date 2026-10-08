import type { AuthTenant, AuthUser, LoginResponse, RegisterResponse } from '../types/auth';

export class AuthContractError extends Error {
  constructor(message: string) {
    super(`Invalid auth API contract: ${message}`);
    this.name = 'AuthContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new AuthContractError(`${path} must be an object.`);
  }
  return value;
}

function requireString(record: Record<string, unknown>, field: string): string {
  const value = record[field];
  if (typeof value !== 'string' || value.length === 0) {
    throw new AuthContractError(`${field} must be a non-empty string.`);
  }
  return value;
}

function requireNonNegativeInteger(
  record: Record<string, unknown>,
  field: string,
): number {
  const value = record[field];
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new AuthContractError(`${field} must be a non-negative integer.`);
  }
  return value;
}

function parseTenant(value: unknown): AuthTenant | null {
  if (value === null) return null;
  const tenant = requireRecord(value, 'tenant');
  const slug = tenant.slug;
  if (slug !== undefined && typeof slug !== 'string') {
    throw new AuthContractError('tenant.slug must be a string when present.');
  }
  return {
    id: requireNonNegativeInteger(tenant, 'id'),
    name: requireString(tenant, 'name'),
    ...(slug !== undefined ? { slug } : {}),
  };
}

export function parseAuthUser(value: unknown): AuthUser {
  const record = requireRecord(value, 'user');
  return {
    id: requireNonNegativeInteger(record, 'id'),
    email: requireString(record, 'email'),
    role: requireString(record, 'role'),
    tenant: parseTenant(record.tenant),
  };
}

export function parseRegisterResponse(value: unknown): RegisterResponse {
  const record = requireRecord(value, 'register response');
  return {
    id: requireNonNegativeInteger(record, 'id'),
    email: requireString(record, 'email'),
    token: requireString(record, 'token'),
  };
}

export function parseLoginResponse(value: unknown): LoginResponse {
  const record = requireRecord(value, 'login response');
  return {
    access_token: requireString(record, 'access_token'),
    token_type: requireString(record, 'token_type'),
  };
}
