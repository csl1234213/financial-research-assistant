import { ApiClientError, deleteJson, getJson } from './client';
import {
  buildConversationDeletePath,
  buildConversationDetailPath,
  parseConversationDeleteResult,
  parseConversationDetail,
  parseConversationList,
} from './agentSessionContract';
import type {
  ConversationDeleteResult,
  ConversationDetail,
  ConversationList,
} from '../types/conversation';

const CLEAR_BATCH_SIZE = 25;

export async function getConversationHistory(
  limit = 50,
): Promise<ConversationList> {
  const payload = await getJson(
    `/v1/agent/sessions?limit=${limit}&offset=0`,
  );
  return parseConversationList(payload);
}

export async function getConversation(
  threadId: string,
  messageCount: number,
): Promise<ConversationDetail> {
  const payload = await getJson(
    buildConversationDetailPath(threadId, messageCount),
  );
  return parseConversationDetail(payload);
}

export async function deleteConversation(
  threadId: string,
): Promise<ConversationDeleteResult> {
  const payload = await deleteJson(
    buildConversationDeletePath(threadId),
  );
  return parseConversationDeleteResult(payload);
}

async function deleteConversationIfPresent(threadId: string): Promise<void> {
  try {
    await deleteConversation(threadId);
  } catch (error: unknown) {
    if (error instanceof ApiClientError && error.status === 404) {
      return;
    }
    throw error;
  }
}

export async function clearConversationHistory(): Promise<number> {
  let deletedCount = 0;

  while (true) {
    const history = await getConversationHistory(CLEAR_BATCH_SIZE);
    if (history.items.length === 0) {
      return deletedCount;
    }

    const results = await Promise.allSettled(
      history.items.map(async (session) => {
        await deleteConversationIfPresent(session.threadId);
      }),
    );
    deletedCount += results.filter(
      (result) => result.status === 'fulfilled',
    ).length;

    const failure = results.find((result) => result.status === 'rejected');
    if (failure?.status === 'rejected') {
      throw failure.reason;
    }
  }
}
