import type { KnowledgeDocument } from '../types/knowledge';

export interface DocumentQuota {
  used: number;
  limit: number;
  remaining: number;
  bypassed: boolean;
}

export type DocumentTaskStatus = 'pending' | 'running' | 'success' | 'failed';

export interface UploadResponse {
  message: string;
  file: string;
  document_id: number;
  task_id: string;
  status: DocumentTaskStatus;
}

export interface TaskResponse {
  id: string;
  status: DocumentTaskStatus;
  progress: number;
  error: string | null;
}

export interface DeleteDocumentResponse {
  deleted: true;
  document_id: number;
}

export type DiscoveryStatus = 'downloaded' | 'already_present';

export interface DiscoveryResponse {
  status: DiscoveryStatus;
  message?: string;
  filename: string;
  document_id: number;
  task_id?: string;
  company: string;
  period?: string;
  source_url?: string;
  source_type?: 'sec_edgar' | 'cninfo';
  source_form?: '10-K' | '10-Q';
  source_stock_code?: string;
  source_exchange?: 'sse' | 'szse' | 'bj';
  source_report_type?: 'annual';
  source_report_year?: number;
  source_audited?: boolean;
}

export class KnowledgeContractError extends Error {
  constructor(message: string) {
    super(`Invalid knowledge API contract: ${message}`);
    this.name = 'KnowledgeContractError';
  }
}

export const MAX_PDF_UPLOAD_BYTES = 50 * 1024 * 1024;
export const MAX_DOCUMENT_UPLOAD_BYTES = MAX_PDF_UPLOAD_BYTES;
export const SUPPORTED_DOCUMENT_EXTENSIONS = ['.pdf', '.xlsx', '.docx', '.csv'] as const;

export type PdfUploadValidationIssue = 'invalid-type' | 'too-large';

interface UploadCandidate {
  name: string;
  size: number;
}

export function validatePdfUpload(
  file: UploadCandidate,
): PdfUploadValidationIssue | null {
  if (!file.name.trim().toLowerCase().endsWith('.pdf')) {
    return 'invalid-type';
  }
  if (file.size > MAX_PDF_UPLOAD_BYTES) {
    return 'too-large';
  }
  return null;
}

export function validateDocumentUpload(
  file: UploadCandidate,
): PdfUploadValidationIssue | null {
  const extension = file.name.trim().toLowerCase().slice(file.name.lastIndexOf('.'));
  if (!(SUPPORTED_DOCUMENT_EXTENSIONS as readonly string[]).includes(extension)) {
    return 'invalid-type';
  }
  if (file.size > MAX_DOCUMENT_UPLOAD_BYTES) {
    return 'too-large';
  }
  return null;
}

export function isKnowledgeRecord(
  value: unknown,
): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function requireRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isKnowledgeRecord(value) || Array.isArray(value)) {
    throw new KnowledgeContractError(`${path} must be an object.`);
  }
  return value;
}

function requireString(
  record: Record<string, unknown>,
  field: string,
): string {
  const value = record[field];
  if (typeof value !== 'string' || value.length === 0) {
    throw new KnowledgeContractError(`${field} must be a non-empty string.`);
  }
  return value;
}

function requireNonNegativeInteger(
  record: Record<string, unknown>,
  field: string,
): number {
  const value = record[field];
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new KnowledgeContractError(
      `${field} must be a non-negative integer.`,
    );
  }
  return value;
}

function requireTaskStatus(
  record: Record<string, unknown>,
  field: string,
): DocumentTaskStatus {
  const value = record[field];
  if (
    value !== 'pending'
    && value !== 'running'
    && value !== 'success'
    && value !== 'failed'
  ) {
    throw new KnowledgeContractError(`${field} is not a supported task status.`);
  }
  return value;
}

export function parseDocumentQuota(value: unknown): DocumentQuota {
  const record = requireRecord(value, 'quota');
  const bypassed = record.bypassed;
  if (typeof bypassed !== 'boolean') {
    throw new KnowledgeContractError('bypassed must be a boolean.');
  }
  return {
    used: requireNonNegativeInteger(record, 'used'),
    limit: requireNonNegativeInteger(record, 'limit'),
    remaining: requireNonNegativeInteger(record, 'remaining'),
    bypassed,
  };
}

export function parseUploadResponse(value: unknown): UploadResponse {
  const record = requireRecord(value, 'upload response');
  return {
    message: requireString(record, 'message'),
    file: requireString(record, 'file'),
    document_id: requireNonNegativeInteger(record, 'document_id'),
    task_id: requireString(record, 'task_id'),
    status: requireTaskStatus(record, 'status'),
  };
}

export function parseTaskResponse(value: unknown): TaskResponse {
  const record = requireRecord(value, 'task response');
  const progress = record.progress;
  if (
    typeof progress !== 'number'
    || !Number.isFinite(progress)
    || progress < 0
    || progress > 100
  ) {
    throw new KnowledgeContractError(
      'progress must be a finite number between 0 and 100.',
    );
  }
  const error = record.error;
  if (error !== null && typeof error !== 'string') {
    throw new KnowledgeContractError('error must be a string or null.');
  }
  return {
    id: requireString(record, 'id'),
    status: requireTaskStatus(record, 'status'),
    progress,
    error,
  };
}

export function parseDeleteDocumentResponse(
  value: unknown,
): DeleteDocumentResponse {
  const record = requireRecord(value, 'delete response');
  if (record.deleted !== true) {
    throw new KnowledgeContractError('deleted must be true.');
  }
  return {
    deleted: true,
    document_id: requireNonNegativeInteger(record, 'document_id'),
  };
}

export function parseDiscoveryResponse(value: unknown): DiscoveryResponse {
  const record = requireRecord(value, 'discovery response');
  const status = record.status;
  if (status !== 'downloaded' && status !== 'already_present') {
    throw new KnowledgeContractError('status is not a supported discovery status.');
  }
  const sourceUrl = record.source_url;
  if (sourceUrl !== undefined && typeof sourceUrl !== 'string') {
    throw new KnowledgeContractError('source_url must be a string when provided.');
  }
  return {
    status,
    message: typeof record.message === 'string' ? record.message : undefined,
    filename: requireString(record, 'filename'),
    document_id: requireNonNegativeInteger(record, 'document_id'),
    task_id: typeof record.task_id === 'string' ? record.task_id : undefined,
    company: requireString(record, 'company'),
    period: typeof record.period === 'string' ? record.period : undefined,
    source_url: sourceUrl as string | undefined,
    source_type: record.source_type === 'sec_edgar' || record.source_type === 'cninfo'
      ? record.source_type
      : undefined,
    source_form: record.source_form === '10-K' || record.source_form === '10-Q'
      ? record.source_form
      : undefined,
    source_stock_code: typeof record.source_stock_code === 'string'
      ? record.source_stock_code
      : undefined,
    source_exchange: record.source_exchange === 'sse'
      || record.source_exchange === 'szse'
      || record.source_exchange === 'bj'
      ? record.source_exchange
      : undefined,
    source_report_type: record.source_report_type === 'annual'
      ? 'annual'
      : undefined,
    source_report_year: typeof record.source_report_year === 'number'
      && Number.isInteger(record.source_report_year)
      ? record.source_report_year
      : undefined,
    source_audited: typeof record.source_audited === 'boolean'
      ? record.source_audited
      : undefined,
  };
}

export function formatByteSize(byteSize: number): string {
  if (byteSize < 1024) return `${byteSize} B`;
  if (byteSize < 1024 * 1024) {
    return `${(byteSize / 1024).toFixed(1)} KB`;
  }
  return `${(byteSize / (1024 * 1024)).toFixed(1)} MB`;
}

function mapFilename(filename: string): KnowledgeDocument {
  return {
    id: filename,
    filename,
    // Legacy filename-only payloads do not provide content-derived issuer
    // metadata. Never promote a filename into an authoritative company.
    company: 'Unknown',
    status: 'indexed',
    pages: 0,
    uploadedAt: '',
    canDelete: false,
  };
}

export function mapKnowledgeDocument(
  value: unknown,
): KnowledgeDocument | null {
  if (typeof value === 'string') {
    return mapFilename(value);
  }
  if (
    !isKnowledgeRecord(value)
    || typeof value.filename !== 'string'
  ) {
    return null;
  }

  const status = value.status === 'ready' || value.status === 'indexed'
    ? 'indexed'
    : value.status === 'processing' || value.status === 'registered' || value.status === 'pending'
      ? 'processing'
      : value.status === 'quarantined'
        ? 'quarantined'
        : 'failed'; // Unknown or absent status must never imply query readiness.
  const byteSize = typeof value.byte_size === 'number'
    ? value.byte_size
    : typeof value.byteSize === 'number'
      ? value.byteSize
      : undefined;
  const contentSha256 = typeof value.content_sha256 === 'string'
    ? value.content_sha256
    : typeof value.contentSha256 === 'string'
      ? value.contentSha256
      : undefined;

  return {
    id: String(value.id ?? value.filename),
    filename: value.filename,
    company: typeof value.company === 'string' ? value.company : 'Unknown',
    period: typeof value.period === 'string' ? value.period : undefined,
    status,
    pages: typeof value.pages === 'number' ? value.pages : 0,
    byteSize,
    size: byteSize === undefined ? undefined : formatByteSize(byteSize),
    chunkCount: typeof value.chunk_count === 'number'
      ? value.chunk_count
      : typeof value.chunkCount === 'number'
        ? value.chunkCount
        : 0,
    contentSha256,
    sourceUrl: typeof value.source_url === 'string'
      ? value.source_url
      : typeof value.sourceUrl === 'string'
        ? value.sourceUrl
        : undefined,
    ...(value.source_type === 'sec_edgar' || value.source_type === 'cninfo'
      ? { sourceType: value.source_type }
      : {}),
    canDelete: value.can_delete === true || value.canDelete === true,
    uploadedAt: typeof value.uploaded_at === 'string'
      ? value.uploaded_at
      : typeof value.uploadedAt === 'string'
        ? value.uploadedAt
        : '',
  };
}
