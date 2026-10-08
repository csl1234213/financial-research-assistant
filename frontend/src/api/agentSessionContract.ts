import type { ChatMessage } from '../types/api';
import { parseFinancialPresentation } from './financialPresentationContract.ts';
import { parseCitation } from './chatContract.ts';
import type {
  ConversationDeleteResult,
  ConversationDetail,
  ConversationList,
  ConversationSummary,
} from '../types/conversation';

export class AgentSessionContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'AgentSessionContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function requireString(
  record: Record<string, unknown>,
  field: string,
): string {
  const value = record[field];
  if (typeof value !== 'string') {
    throw new AgentSessionContractError(`${field} must be a string.`);
  }
  return value;
}

function requireNonNegativeInteger(
  record: Record<string, unknown>,
  field: string,
): number {
  const value = record[field];
  if (
    typeof value !== 'number'
    || !Number.isInteger(value)
    || value < 0
  ) {
    throw new AgentSessionContractError(
      `${field} must be a non-negative integer.`,
    );
  }
  return value;
}

function requireBoolean(
  record: Record<string, unknown>,
  field: string,
): boolean {
  const value = record[field];
  if (typeof value !== 'boolean') {
    throw new AgentSessionContractError(`${field} must be a boolean.`);
  }
  return value;
}

export function parseConversationSummary(
  value: unknown,
): ConversationSummary {
  if (!isRecord(value)) {
    throw new AgentSessionContractError(
      'Agent session summary must be an object.',
    );
  }

  return {
    threadId: requireString(value, 'thread_id'),
    messageCount: requireNonNegativeInteger(value, 'message_count'),
    createdAt: requireString(value, 'created_at'),
    updatedAt: requireString(value, 'updated_at'),
  };
}

export function parseConversationList(value: unknown): ConversationList {
  if (!isRecord(value) || !Array.isArray(value.items)) {
    throw new AgentSessionContractError(
      'Agent session list must include an items array.',
    );
  }

  return {
    items: value.items.map(parseConversationSummary),
    total: requireNonNegativeInteger(value, 'total'),
    limit: requireNonNegativeInteger(value, 'limit'),
    offset: requireNonNegativeInteger(value, 'offset'),
  };
}

function parseConversationMessage(value: unknown): ChatMessage | null {
  if (!isRecord(value)) {
    throw new AgentSessionContractError(
      'Agent session message must be an object.',
    );
  }

  const id = requireNonNegativeInteger(value, 'id');
  const role = requireString(value, 'role');
  const content = requireString(value, 'content');

  if (role !== 'user' && role !== 'assistant') {
    return null;
  }

  const metadata = isRecord(value.metadata) ? value.metadata : null;
  let citations: ChatMessage['savedCitations'];
  try {
    citations = role === 'assistant' && Array.isArray(metadata?.citations)
      ? metadata.citations.map(parseCitation) : undefined;
  } catch {
    citations = undefined;
  }
  const financialPresentation = role === 'assistant'
    && citations?.some((citation) => citation.rank === 1)
    ? parseFinancialPresentation(metadata?.financial_presentation) : null;
  const duration = metadata?.duration_ms;
  const durationMs = role === 'assistant'
    && typeof duration === 'number'
    && Number.isFinite(duration)
    && duration >= 0
    ? duration
    : undefined;

  return {
    id: `session-message-${id}`,
    role,
    content,
    financialPresentation,
    savedCitations: citations,
    citationNamespace: `session-message-${id}`,
    ...(durationMs !== undefined ? { durationMs } : {}),
  };
}

export function parseConversationDetail(value: unknown): ConversationDetail {
  if (!isRecord(value) || !Array.isArray(value.messages)) {
    throw new AgentSessionContractError(
      'Agent session detail must include a messages array.',
    );
  }

  const messages = value.messages
    .map(parseConversationMessage)
    .filter((message): message is ChatMessage => message !== null);

  return {
    session: parseConversationSummary(value.session),
    messages,
    totalMessages: requireNonNegativeInteger(value, 'total_messages'),
    limit: requireNonNegativeInteger(value, 'limit'),
    offset: requireNonNegativeInteger(value, 'offset'),
  };
}

export function parseConversationDeleteResult(
  value: unknown,
): ConversationDeleteResult {
  if (!isRecord(value) || value.deleted !== true) {
    throw new AgentSessionContractError(
      'Agent session deletion must confirm deleted=true.',
    );
  }

  return {
    deleted: true,
    threadId: requireString(value, 'thread_id'),
    messagesDeleted: requireNonNegativeInteger(value, 'messages_deleted'),
    checkpointsArchived: requireNonNegativeInteger(
      value,
      'checkpoints_archived',
    ),
    runtimeCheckpointsDeleted: requireBoolean(
      value,
      'runtime_checkpoints_deleted',
    ),
    cacheKeysDeleted: requireNonNegativeInteger(value, 'cache_keys_deleted'),
  };
}

export function buildConversationDetailPath(
  threadId: string,
  messageCount: number,
): string {
  const offset = Math.max(0, messageCount - 500);
  return `/v1/agent/sessions/${encodeURIComponent(threadId)}`
    + `?message_limit=500&message_offset=${offset}`;
}

export function buildConversationDeletePath(threadId: string): string {
  return `/v1/agent/sessions/${encodeURIComponent(threadId)}`;
}
