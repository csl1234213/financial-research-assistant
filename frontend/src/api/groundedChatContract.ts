import type { Language } from '../types/language';

/** READY job identity is required; never silently fall back to ordinary RAG. */
export function createGroundedChatRequest(
  ingestionJobId: string,
  question: string,
  answerLanguage: Language,
  stream = false,
  additionalIngestionJobIds: string[] = [],
) {
  if (typeof ingestionJobId !== 'string' || !ingestionJobId.trim() || ingestionJobId.length > 128) {
    throw new Error('A valid ingestion job is required.');
  }
  if (typeof question !== 'string' || !question.trim() || question.length > 4000) {
    throw new Error('A valid financial question is required.');
  }
  if (answerLanguage !== 'zh-CN' && answerLanguage !== 'en') {
    throw new Error('Unsupported answer language.');
  }
  if (typeof stream !== 'boolean') throw new Error('Invalid streaming option.');
  if (!Array.isArray(additionalIngestionJobIds) || additionalIngestionJobIds.length > 4
    || additionalIngestionJobIds.some(id => typeof id !== 'string' || !id.trim() || id !== id.trim() || id.length > 128)
    || new Set([ingestionJobId, ...additionalIngestionJobIds]).size !== additionalIngestionJobIds.length + 1) {
    throw new Error('Invalid additional report selection.');
  }
  return { ingestion_job_id: ingestionJobId, question, answer_language: answerLanguage, stream,
    ...(additionalIngestionJobIds.length ? { additional_ingestion_job_ids: [...additionalIngestionJobIds] } : {}) };
}
