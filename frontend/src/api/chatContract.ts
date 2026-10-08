import type {
  ChatResponse,
  Citation,
  Execution,
  Plan,
  Planning,
  Reasoning,
  Routing,
  Workflow,
} from '../types/api';
import type { Language } from '../types/language';
import { parseFinancialPresentation } from './financialPresentationContract.ts';

export interface ChatRequest {
  question: string;
  answer_language?: Language;
  company?: string;
  thread_id?: string;
  stream?: boolean;
}

export class ChatContractError extends Error {
  constructor(message: string) {
    super(`Invalid chat API contract: ${message}`);
    this.name = 'ChatContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function requireRecord(
  value: unknown,
  path: string,
): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new ChatContractError(`${path} must be an object`);
  }
  return value;
}

function requireString(value: unknown, path: string): string {
  if (typeof value !== 'string') {
    throw new ChatContractError(`${path} must be a string`);
  }
  return value;
}

function requireFiniteNumber(value: unknown, path: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new ChatContractError(`${path} must be a finite number`);
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
    throw new ChatContractError(`${path}.${field} must be a string when present`);
  }
  return value;
}

function optionalNonNegativeInteger(
  record: Record<string, unknown>,
  field: string,
  path: string,
): number | undefined {
  const value = record[field];
  if (
    value !== undefined
    && (typeof value !== 'number' || !Number.isInteger(value) || value < 0)
  ) {
    throw new ChatContractError(
      `${path}.${field} must be a non-negative integer when present`,
    );
  }
  return value;
}

function requireStringArray(value: unknown, path: string): string[] {
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
    throw new ChatContractError(`${path} must be an array of strings`);
  }
  return value.filter((item): item is string => typeof item === 'string');
}

export function parseCitation(value: unknown, index: number): Citation {
  const path = `citations[${index}]`;
  const citation = requireRecord(value, path);
  const rank = requireFiniteNumber(citation.rank, `${path}.rank`);

  if (!Number.isInteger(rank) || rank < 1) {
    throw new ChatContractError(`${path}.rank must be a positive integer`);
  }

  const source = requireString(citation.source, `${path}.source`);
  const chunkId = requireString(citation.chunk_id, `${path}.chunk_id`);
  const preview = requireString(citation.preview, `${path}.preview`);

  const similarityValue = citation.similarity;
  const similarity = similarityValue === null
    ? null
    : requireFiniteNumber(similarityValue, `${path}.similarity`);

  const page = optionalNonNegativeInteger(citation, 'page', path);
  const pageLabel = optionalString(citation, 'page_label', path);
  const sourceLocator = optionalString(citation, 'source_locator', path);
  const contentType = optionalString(citation, 'content_type', path);
  const sourceFormat = optionalString(citation, 'source_format', path);
  const documentId = optionalString(citation, 'document_id', path);
  const contentSha256 = optionalString(citation, 'content_sha256', path);
  if (contentSha256 !== undefined && !/^[a-f0-9]{64}$/.test(contentSha256)) {
    throw new ChatContractError(`${path}.content_sha256 must be a SHA-256 digest`);
  }

  return {
    rank,
    source,
    chunk_id: chunkId,
    similarity,
    preview,
    ...(page === undefined ? {} : { page }),
    ...(pageLabel === undefined ? {} : { page_label: pageLabel }),
    ...(sourceLocator === undefined ? {} : { source_locator: sourceLocator }),
    ...(contentType === undefined ? {} : { content_type: contentType }),
    ...(sourceFormat === undefined ? {} : { source_format: sourceFormat }),
    ...(documentId === undefined ? {} : { document_id: documentId }),
    ...(contentSha256 === undefined ? {} : { content_sha256: contentSha256 }),
  };
}

function parseReasoning(value: unknown): Reasoning {
  const reasoning = requireRecord(value, 'reasoning');
  const intent = requireString(reasoning.intent, 'reasoning.intent');
  const researchMode = requireString(
    reasoning.research_mode,
    'reasoning.research_mode',
  );
  const evidenceCount = requireFiniteNumber(
    reasoning.evidence_count,
    'reasoning.evidence_count',
  );
  if (!Number.isInteger(evidenceCount) || evidenceCount < 0) {
    throw new ChatContractError(
      'reasoning.evidence_count must be a non-negative integer',
    );
  }

  const companies = requireStringArray(reasoning.companies, 'reasoning.companies');

  return {
    intent,
    research_mode: researchMode,
    evidence_count: evidenceCount,
    companies,
  };
}

function parsePlan(value: unknown): Plan {
  const plan = requireRecord(value, 'plan');
  const steps = plan.steps;
  if (
    steps !== undefined
    && (!Array.isArray(steps) || !steps.every((step) => typeof step === 'string'))
  ) {
    throw new ChatContractError('plan.steps must be an array of strings when present');
  }
  const queries = plan.queries;
  if (
    queries !== undefined
    && (!Array.isArray(queries) || !queries.every((query) => typeof query === 'string'))
  ) {
    throw new ChatContractError('plan.queries must be an array of strings when present');
  }
  return {
    ...plan,
    ...(steps === undefined ? {} : { steps }),
    ...(queries === undefined ? {} : { queries }),
  };
}

function parseNullableRecord<T>(
  value: unknown,
  path: string,
  parse: (record: Record<string, unknown>) => T,
): T | null {
  if (value === null) {
    return null;
  }

  const record = requireRecord(value, path);
  return parse(record);
}

export function createChatRequest(
  question: string,
  company?: string,
  threadId?: string,
  answerLanguage?: Language,
  stream = false,
): ChatRequest {
  const normalizedQuestion = question.trim();
  if (!normalizedQuestion) {
    throw new ChatContractError('question must not be empty');
  }

  const request: ChatRequest = {
    question: normalizedQuestion,
    ...(answerLanguage ? { answer_language: answerLanguage } : {}),
    ...(stream ? { stream: true } : {}),
  };
  const normalizedCompany = company?.trim();
  if (normalizedCompany) {
    request.company = normalizedCompany;
  }
  const normalizedThreadId = threadId?.trim();
  if (normalizedThreadId) {
    request.thread_id = normalizedThreadId;
  }
  return request;
}

export function parseChatResponse(value: unknown): ChatResponse {
  const response = requireRecord(value, 'response');
  requireString(response.report, 'report');
  requireRecord(response.plan, 'plan');
  requireFiniteNumber(response.execution_time, 'execution_time');

  if (!Array.isArray(response.citations)) {
    throw new ChatContractError('citations must be an array');
  }
  const citations = response.citations.map(parseCitation);
  const reasoning = parseReasoning(response.reasoning);

  const routing = parseNullableRecord<Routing>(
    response.routing,
    'routing',
    (record) => {
      const agent = optionalString(record, 'agent', 'routing');
      const pipeline = optionalString(record, 'pipeline', 'routing');
      const model = optionalString(record, 'model', 'routing');
      return {
        provider: requireString(record.provider, 'routing.provider'),
        ...(agent === undefined ? {} : { agent }),
        ...(pipeline === undefined ? {} : { pipeline }),
        ...(model === undefined ? {} : { model }),
      };
    },
  );
  const planning = parseNullableRecord<Planning>(
    response.planning,
    'planning',
    (record) => {
      const intent = optionalString(record, 'intent', 'planning');
      const researchMode = optionalString(record, 'research_mode', 'planning');
      const companies = record.companies;
      if (
        companies !== undefined
        && (!Array.isArray(companies)
          || !companies.every((company) => typeof company === 'string'))
      ) {
        throw new ChatContractError(
          'planning.companies must be an array of strings',
        );
      }
      return {
        ...(intent === undefined ? {} : { intent }),
        ...(researchMode === undefined ? {} : { research_mode: researchMode }),
        ...(companies === undefined ? {} : { companies }),
      };
    },
  );
  const execution = parseNullableRecord<Execution>(
    response.execution,
    'execution',
    (record) => ({
      ...record,
      strategy: requireString(record.strategy, 'execution.strategy'),
    }),
  );
  const workflow = parseNullableRecord<Workflow>(
    response.workflow,
    'workflow',
    (record) => {
      return {
        ...record,
        type: requireString(record.type, 'workflow.type'),
        status: requireString(record.status, 'workflow.status'),
      };
    },
  );

  return {
    report: requireString(response.report, 'report'),
    plan: parsePlan(response.plan),
    execution_time: requireFiniteNumber(response.execution_time, 'execution_time'),
    citations,
    reasoning,
    routing,
    planning,
    execution,
    workflow,
    financialPresentation: execution?.strategy === 'structured_financial_fact'
      && execution.status === 'FOUND'
      && execution.provider_calls === 0
      && workflow?.type === 'structured_financial_fact'
      && workflow.status === 'completed'
      && citations.some((citation) => citation.rank === 1)
      ? parseFinancialPresentation(
      (response.planning as { structured_financial_query?: { financial_presentation?: unknown } } | null)
        ?.structured_financial_query?.financial_presentation,
    ) : null,
  };
}
