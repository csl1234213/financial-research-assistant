import {
  ApiClientError,
  getAuthorizationHeaders,
  postJson,
  toApiUrl,
} from './client';
import {
  createChatRequest,
  parseChatResponse,
} from './chatContract';
import type { ChatResponse } from '../types/chat';
import type { Language } from '../types/language';
import { createGroundedChatRequest } from './groundedChatContract';

const chatEndpoint = '/v1/chat';

type StreamCallback = (delta: string) => void;

async function sendStreamingChat(
  request: ReturnType<typeof createChatRequest> | ReturnType<typeof createGroundedChatRequest>,
  onDelta: StreamCallback,
  endpoint = chatEndpoint,
): Promise<ChatResponse> {
  let response: Response;
  try {
    response = await fetch(toApiUrl(endpoint), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...getAuthorizationHeaders(),
      },
      body: JSON.stringify(request),
    });
  } catch (error: unknown) {
    throw new ApiClientError(
      error instanceof Error ? error.message : 'Network request failed.',
    );
  }

  if (!response.ok) {
    const raw = await response.text();
    let message = `Request failed with status ${response.status}.`;
    try {
      const payload: unknown = JSON.parse(raw);
      if (typeof payload === 'object' && payload !== null && 'detail' in payload) {
        const detail = (payload as { detail?: unknown }).detail;
        if (typeof detail === 'string') message = detail;
      }
    } catch {
      // Keep the stable status-based message for non-JSON error responses.
    }
    throw new ApiClientError(message, response.status);
  }

  if (!response.body) {
    throw new ApiClientError('The browser does not support streaming responses.');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventName = 'message';
  let dataLines: string[] = [];
  let completed: ChatResponse | null = null;

  const dispatchEvent = () => {
    if (dataLines.length === 0) return;
    const rawData = dataLines.join('\n');
    dataLines = [];
    let payload: unknown;
    try {
      payload = JSON.parse(rawData) as unknown;
    } catch {
      throw new ApiClientError('The server sent an invalid streaming event.');
    }

    if (eventName === 'delta') {
      if (
        typeof payload !== 'object'
        || payload === null
        || !('text' in payload)
        || typeof (payload as { text?: unknown }).text !== 'string'
      ) {
        throw new ApiClientError('The server sent an invalid answer fragment.');
      }
      onDelta((payload as { text: string }).text);
    } else if (eventName === 'complete') {
      completed = parseChatResponse(payload);
    } else if (eventName === 'error') {
      const detail = typeof payload === 'object' && payload !== null
        && 'detail' in payload
        && typeof (payload as { detail?: unknown }).detail === 'string'
        ? (payload as { detail: string }).detail
        : 'The chat stream failed.';
      throw new ApiClientError(detail);
    }
    eventName = 'message';
  };

  const consumeLine = (line: string) => {
    if (line === '') {
      dispatchEvent();
      return;
    }
    if (line.startsWith(':')) return;
    const separator = line.indexOf(':');
    const field = separator < 0 ? line : line.slice(0, separator);
    const value = separator < 0 ? '' : line.slice(separator + 1).replace(/^ /, '');
    if (field === 'event') eventName = value;
    if (field === 'data') dataLines.push(value);
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split(/\r?\n/);
    buffer = lines.pop() ?? '';
    for (const line of lines) consumeLine(line);
    if (done) break;
  }
  if (buffer) consumeLine(buffer);
  dispatchEvent();

  if (!completed) {
    throw new ApiClientError('The chat stream ended before completion.');
  }
  return completed;
}

export async function sendChatMessage(
  question: string,
  company?: string,
  threadId?: string,
  answerLanguage?: Language,
  onDelta?: StreamCallback,
): Promise<ChatResponse> {
  const request = createChatRequest(
    question,
    company,
    threadId,
    answerLanguage,
    Boolean(onDelta),
  );
  if (onDelta) return sendStreamingChat(request, onDelta);

  const payload = await postJson(
    chatEndpoint,
    request,
  );
  return parseChatResponse(payload);
}

/** Explicit isolated pilot path. The server owns readiness and evidence checks. */
export async function sendGroundedChatMessage(
  ingestionJobId: string,
  question: string,
  answerLanguage: Language,
  onDelta?: StreamCallback,
  additionalIngestionJobIds: string[] = [],
): Promise<ChatResponse> {
  const request = createGroundedChatRequest(ingestionJobId, question, answerLanguage, Boolean(onDelta),
    additionalIngestionJobIds);
  const endpoint = '/v1/grounded-chat';
  if (onDelta) return sendStreamingChat(request, onDelta, endpoint);
  return parseChatResponse(await postJson(endpoint, request));
}
