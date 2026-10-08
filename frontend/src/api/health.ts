import { ApiClientError, toApiUrl } from './client';
import { parseHealthResponse } from './healthContract';
import type { HealthResponse } from '../types/api';

const healthEndpoint = '/v1/health';

function parseJson(text: string): unknown | undefined {
  if (!text) return undefined;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

export async function getHealth(): Promise<HealthResponse> {
  let response: Response;

  try {
    response = await fetch(toApiUrl(healthEndpoint));
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : 'Network request failed.';
    throw new ApiClientError(message);
  }

  const payload = parseJson(await response.text());

  if (!response.ok) {
    const fallback = `Health check failed with status ${response.status}.`;
    const detail = isRecord(payload) ? payload.detail : undefined;
    const message = typeof detail === 'string' ? detail : fallback;
    throw new ApiClientError(message, response.status, payload);
  }

  if (payload === undefined) {
    throw new ApiClientError('The API returned an invalid JSON response.', response.status);
  }

  return parseHealthResponse(payload);
}
