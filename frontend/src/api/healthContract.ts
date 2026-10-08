import type { HealthResponse } from '../types/api';

export class HealthContractError extends Error {
  constructor(message: string) {
    super(`Invalid health API contract: ${message}`);
    this.name = 'HealthContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export function parseHealthResponse(value: unknown): HealthResponse {
  if (!isRecord(value)) {
    throw new HealthContractError('health response must be an object.');
  }
  const status = value.status;
  if (
    status !== 'ok'
    && status !== 'healthy'
    && status !== 'degraded'
    && status !== 'unhealthy'
  ) {
    throw new HealthContractError('status is not supported.');
  }
  if (value.version !== undefined && typeof value.version !== 'string') {
    throw new HealthContractError('version must be a string when present.');
  }
  if (value.uptime !== undefined
    && (typeof value.uptime !== 'number' || !Number.isFinite(value.uptime))) {
    throw new HealthContractError('uptime must be a finite number when present.');
  }

  const components = value.components;
  if (components !== undefined) {
    if (typeof components !== 'object' || components === null || Array.isArray(components)) {
      throw new HealthContractError('components must be an object when present.');
    }
    for (const componentStatus of Object.values(components)) {
      if (
        componentStatus !== 'up'
        && componentStatus !== 'down'
        && componentStatus !== 'degraded'
      ) {
        throw new HealthContractError('components contains an unsupported status.');
      }
    }
  }

  return {
    status,
    ...(typeof value.version === 'string' ? { version: value.version } : {}),
    ...(typeof value.uptime === 'number' ? { uptime: value.uptime } : {}),
    ...(components && typeof components === 'object' && !Array.isArray(components)
      ? { components: components as Record<string, 'up' | 'down' | 'degraded'> }
      : {}),
  };
}
