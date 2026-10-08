import { ApiClientError, toApiUrl } from './client';
import { MOCK_DOCUMENT_DETAILS, MOCK_CHUNKS } from '../types/knowledge';
import type { DocumentDetail, DocumentChunk } from '../types/knowledge';
import { parseDocumentChunks, parseDocumentDetail } from './documentContract';

const knowledgeDetailEndpoint = (id: string) => `/v1/knowledge/${id}`;
const knowledgeChunksEndpoint = (id: string) => `/v1/knowledge/${id}/chunks`;

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

function getErrorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) return fallback;
  const detail = payload.detail;
  if (typeof detail === 'string') return detail;
  const message = payload.message;
  return typeof message === 'string' ? message : fallback;
}

const isMockEnabled = import.meta.env.VITE_ENABLE_MOCK === 'true';

export async function getDocument(id: string): Promise<DocumentDetail> {
  try {
    const response = await fetch(toApiUrl(knowledgeDetailEndpoint(id)));
    const payload = parseJson(await response.text());

    if (!response.ok) {
      throw new ApiClientError(
        getErrorMessage(payload, `Failed to fetch document (${response.status}).`),
        response.status,
        payload,
      );
    }

    if (payload === undefined) {
      throw new ApiClientError('The API returned an invalid JSON response.', response.status);
    }

    return parseDocumentDetail(payload);
  } catch (err) {
    if (isMockEnabled) {
      const mock = MOCK_DOCUMENT_DETAILS[id];
      if (mock) {
        return mock;
      }
      throw new ApiClientError(`Document with id "${id}" not found.`);
    }
    throw err;
  }
}

export async function getDocumentChunks(id: string): Promise<DocumentChunk[]> {
  try {
    const response = await fetch(toApiUrl(knowledgeChunksEndpoint(id)));
    const payload = parseJson(await response.text());

    if (!response.ok) {
      throw new ApiClientError(
        getErrorMessage(payload, `Failed to fetch chunks (${response.status}).`),
        response.status,
        payload,
      );
    }

    if (payload === undefined) {
      throw new ApiClientError('The API returned an invalid JSON response.', response.status);
    }

    const raw = payload;
    if (isRecord(raw) && Array.isArray(raw.chunks)) {
      return parseDocumentChunks(raw.chunks);
    }
    if (Array.isArray(raw)) {
      return parseDocumentChunks(raw);
    }
    throw new ApiClientError('The API returned an invalid chunks response.', response.status);
  } catch (err) {
    if (isMockEnabled) {
      return MOCK_CHUNKS;
    }
    throw err;
  }
}
