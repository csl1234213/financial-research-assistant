import type { ChatMessage } from './api';

export interface ConversationSummary {
  threadId: string;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface ConversationList {
  items: ConversationSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface ConversationDetail {
  session: ConversationSummary;
  messages: ChatMessage[];
  totalMessages: number;
  limit: number;
  offset: number;
}

export interface ConversationDeleteResult {
  deleted: true;
  threadId: string;
  messagesDeleted: number;
  checkpointsArchived: number;
  runtimeCheckpointsDeleted: boolean;
  cacheKeysDeleted: number;
}

export interface ActiveConversation {
  threadId: string;
  kind: 'draft' | 'persisted';
  messages: ChatMessage[];
}
