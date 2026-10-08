import type { DocumentChunk, DocumentDetail, DocumentStatus } from '../types/knowledge';

export class DocumentContractError extends Error {
  constructor(message: string) {
    super(`Invalid document API contract: ${message}`);
    this.name = 'DocumentContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new DocumentContractError(`${path} must be an object.`);
  }
  return value;
}

function requireString(
  record: Record<string, unknown>,
  field: string,
  path: string,
): string {
  const value = record[field];
  if (typeof value !== 'string') {
    throw new DocumentContractError(`${path}.${field} must be a string.`);
  }
  return value;
}

function requireNonNegativeInteger(
  record: Record<string, unknown>,
  field: string,
  path: string,
): number {
  const value = record[field];
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new DocumentContractError(
      `${path}.${field} must be a non-negative integer.`,
    );
  }
  return value;
}

function parseStatus(
  record: Record<string, unknown>,
  field: string,
  path: string,
): DocumentStatus {
  const value = record[field];
  if (value !== 'indexed' && value !== 'processing' && value !== 'failed') {
    throw new DocumentContractError(`${path}.${field} is not a supported status.`);
  }
  return value;
}

function optionalString(
  record: Record<string, unknown>,
  field: string,
  path: string,
): string | undefined {
  const value = record[field];
  if (value !== undefined && typeof value !== 'string') {
    throw new DocumentContractError(`${path}.${field} must be a string when present.`);
  }
  return value;
}

function optionalNumber(
  record: Record<string, unknown>,
  field: string,
  path: string,
): number | undefined {
  const value = record[field];
  if (
    value !== undefined
    && (typeof value !== 'number' || !Number.isFinite(value))
  ) {
    throw new DocumentContractError(`${path}.${field} must be finite when present.`);
  }
  return value;
}

export function parseDocumentDetail(value: unknown): DocumentDetail {
  const record = requireRecord(value, 'document');
  const path = 'document';
  const chunkCount = requireNonNegativeInteger(record, 'chunk_count', path);
  const embeddingStatus = record.embedding_status;
  if (
    embeddingStatus !== 'completed'
    && embeddingStatus !== 'pending'
    && embeddingStatus !== 'failed'
  ) {
    throw new DocumentContractError(
      'document.embedding_status is not a supported status.',
    );
  }
  const vectorStatus = record.vector_status;
  if (vectorStatus !== 'stored' && vectorStatus !== 'pending' && vectorStatus !== 'failed') {
    throw new DocumentContractError(
      'document.vector_status is not a supported status.',
    );
  }
  const size = optionalString(record, 'size', path);
  const fileSize = optionalString(record, 'file_size', path);
  const createdAt = optionalString(record, 'created_at', path);
  const updatedAt = optionalString(record, 'updated_at', path);
  return {
    id: requireString(record, 'id', path),
    filename: requireString(record, 'filename', path),
    company: requireString(record, 'company', path),
    period: optionalString(record, 'period', path),
    pages: requireNonNegativeInteger(record, 'pages', path),
    status: parseStatus(record, 'status', path),
    uploadedAt: requireString(record, 'uploaded_at', path),
    size,
    chunkCount,
    embeddingStatus,
    vectorStatus,
    fileSize,
    createdAt,
    updatedAt,
  };
}

function parseChunk(value: unknown, index: number): DocumentChunk {
  const path = `chunks[${index}]`;
  const record = requireRecord(value, path);
  const metadata = record.metadata;
  if (!isRecord(metadata)) {
    throw new DocumentContractError(`${path}.metadata must be an object.`);
  }
  const normalizedMetadata: Record<string, string> = {};
  for (const [key, item] of Object.entries(metadata)) {
    if (typeof item !== 'string') {
      throw new DocumentContractError(`${path}.metadata.${key} must be a string.`);
    }
    normalizedMetadata[key] = item;
  }
  const score = optionalNumber(record, 'score', path);
  return {
    index: requireNonNegativeInteger(record, 'index', path),
    content: requireString(record, 'content', path),
    metadata: normalizedMetadata,
    ...(score === undefined ? {} : { score }),
  };
}

export function parseDocumentChunks(value: unknown): DocumentChunk[] {
  if (!Array.isArray(value)) {
    throw new DocumentContractError('chunks must be an array.');
  }
  return value.map(parseChunk);
}
