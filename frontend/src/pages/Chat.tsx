import {
  useState,
  useCallback,
  useEffect,
  useRef,
} from 'react';
import { Header } from '../components/layout/Header';
import { ChatWindow } from '../components/chat/ChatWindow';
import { InputBox } from '../components/chat/InputBox';
import { ConversationSidebar } from '../components/chat/ConversationSidebar';
import { AgentTimeline } from '../components/agent/AgentTimeline';
import { CitationList } from '../components/citation/CitationList';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { sendChatMessage } from '../api/chat';
import { ApiClientError } from '../api/client';
import { getHealth } from '../api/health';
import { discoverCompanyDocument, uploadDocument } from '../api/knowledge';
import { useLanguage } from '../i18n/LanguageContext';
import {
  extractModelIdentity,
  getRuntimeFailureKind,
} from '../components/chat/reportPresentation';
import type { ChatMessage, ChatResponse } from '../types/api';
import type { ConversationSummary } from '../types/conversation';

const HISTORY_COLLAPSED_STORAGE_KEY = 'financial-rag-history-collapsed';

interface ChatProps {
  threadId: string;
  initialMessages: ChatMessage[];
  activeKind: 'draft' | 'persisted';
  conversationHistory: ConversationSummary[];
  conversationHistoryTotal: number;
  historyLoading: boolean;
  historyClearing: boolean;
  historyError: string | null;
  selectingThreadId: string | null;
  onSelectConversation: (session: ConversationSummary) => void;
  onClearConversationHistory: () => Promise<void>;
  onMessagesChange: (threadId: string, messages: ChatMessage[]) => void;
  onTurnCompleted: (threadId: string) => void;
}

function findLatestResponse(messages: ChatMessage[]): ChatResponse | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    if (messages[index].response) {
      return messages[index].response ?? null;
    }
  }
  return null;
}

function formatProviderName(provider: string): string {
  const knownProviders: Record<string, string> = {
    deepseek: 'DeepSeek',
    gemini: 'Gemini',
    openai: 'OpenAI / ChatGPT',
    anthropic: 'Anthropic Claude',
    doubao: '豆包',
  };
  return knownProviders[provider.toLowerCase()] ?? provider;
}

export function Chat({
  threadId,
  initialMessages,
  activeKind,
  conversationHistory,
  conversationHistoryTotal,
  historyLoading,
  historyClearing,
  historyError,
  selectingThreadId,
  onSelectConversation,
  onClearConversationHistory,
  onMessagesChange,
  onTurnCompleted,
}: ChatProps) {
  const { language, t } = useLanguage();
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const messagesRef = useRef(initialMessages);
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<ChatResponse | null>(
    () => findLatestResponse(initialMessages),
  );
  const [discoveryStatus, setDiscoveryStatus] = useState<string | null>(null);
  const [backendConnected, setBackendConnected] = useState(false);
  const [historyCollapsed, setHistoryCollapsed] = useState(
    () => window.localStorage.getItem(HISTORY_COLLAPSED_STORAGE_KEY) === 'true',
  );
  const modelIdentity = extractModelIdentity(response?.routing);
  const runtimeFailed = response !== null
    && getRuntimeFailureKind(response.report) !== null;
  const showInsights = loading || response !== null;

  let runtimeStatus = t.chat.apiOffline;
  let runtimeStatusState = 'offline';
  if (backendConnected) {
    runtimeStatus = t.chat.apiReady;
    runtimeStatusState = 'ready';
  }
  if (response) {
    runtimeStatus = t.chat.analysisCompleted;
    runtimeStatusState = 'completed';
  }
  if (modelIdentity) {
    runtimeStatus = t.chat.modelCompleted(
      formatProviderName(modelIdentity.provider),
      modelIdentity.model,
    );
    runtimeStatusState = 'completed';
  }
  if (runtimeFailed) {
    runtimeStatus = t.chat.modelUnavailable;
    runtimeStatusState = 'failed';
  }
  if (loading) {
    runtimeStatus = t.chat.modelRunning;
    runtimeStatusState = 'running';
  }

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const health = await getHealth();
        if (!cancelled) {
          setBackendConnected(
            health.status === 'ok'
            || health.status === 'healthy'
            || health.status === 'degraded',
          );
        }
      } catch {
        if (!cancelled) {
          setBackendConnected(false);
        }
      }
    }

    checkHealth();
    const timer = setInterval(checkHealth, 30000);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    window.localStorage.setItem(
      HISTORY_COLLAPSED_STORAGE_KEY,
      String(historyCollapsed),
    );
  }, [historyCollapsed]);

  const commitMessages = useCallback((nextMessages: ChatMessage[]) => {
    messagesRef.current = nextMessages;
    setMessages(nextMessages);
    onMessagesChange(threadId, nextMessages);
  }, [onMessagesChange, threadId]);

  const handleSend = useCallback(
    async (question: string) => {
      const startedAt = performance.now();
      const turnId = crypto.randomUUID();
      const userMessage: ChatMessage = {
        id: turnId,
        role: 'user',
        content: question,
      };
      const messagesWithQuestion = [...messagesRef.current, userMessage];

      commitMessages(messagesWithQuestion);
      setLoading(true);
      setResponse(null);
      setDiscoveryStatus(null);

      try {
        let streamedMessageId: string | null = null;
        let streamedContent = '';
        const apiResponse = await sendChatMessage(
          question,
          undefined,
          threadId,
          language,
          (delta) => {
            streamedMessageId = streamedMessageId ?? crypto.randomUUID();
            streamedContent += delta;
            commitMessages([
              ...messagesWithQuestion,
              {
                id: streamedMessageId,
                role: 'assistant',
                content: streamedContent,
                citationNamespace: `chat-turn-${turnId}`,
              },
            ]);
          },
        );
        const failureKind = getRuntimeFailureKind(apiResponse.report);
        const localizedFailure = failureKind === 'provider-disabled'
          ? t.chat.providerDisabled
          : failureKind === 'provider-configuration'
            ? t.chat.providerConfigurationError
            : failureKind === 'provider-error'
              ? t.chat.providerTemporaryError
              : failureKind === 'agent-runtime-fallback'
                ? t.chat.runtimeFallbackError
                : null;
        const report = localizedFailure ?? apiResponse.report;

        setResponse(apiResponse);
        commitMessages([
          ...messagesWithQuestion,
          {
            id: streamedMessageId ?? crypto.randomUUID(),
            role: 'assistant',
            content: report,
            durationMs: performance.now() - startedAt,
            response: apiResponse,
            citationNamespace: `chat-turn-${turnId}`,
          },
        ]);
        const companies = apiResponse.reasoning?.companies ?? [];
        if (apiResponse.citations.length === 0 && companies.length === 1) {
          const company = companies[0];
          setDiscoveryStatus(t.chat.autoDiscoverySearching(company));
          void discoverCompanyDocument(company)
            .then((discovery) => {
              setDiscoveryStatus(
                discovery.status === 'downloaded'
                  ? t.chat.autoDiscoveryDownloaded(company)
                  : t.chat.autoDiscoveryAlreadyPresent(company),
              );
            })
            .catch(() => {
              setDiscoveryStatus(t.chat.autoDiscoveryUnavailable(company));
            });
        }
        onTurnCompleted(threadId);
      } catch (error: unknown) {
        const detail = error instanceof Error ? error.message : t.chat.connectionError;
        commitMessages([
          ...messagesWithQuestion,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: `${t.chat.connectionError}：${detail}`,
            durationMs: performance.now() - startedAt,
          },
        ]);
      } finally {
        setLoading(false);
      }
    },
    [
      commitMessages,
      language,
      onTurnCompleted,
      t,
      threadId,
    ],
  );

  const handlePdfUpload = useCallback(async (file: File) => {
    try {
      await uploadDocument(file);
    } catch (error: unknown) {
      if (error instanceof ApiClientError) {
        if (error.status === 400) {
          throw new Error(t.upload.invalidDocument);
        }
        if (error.status === 409) {
          throw new Error(t.upload.duplicateDocument);
        }
        if (error.status === 413) {
          throw new Error(t.upload.fileTooLarge);
        }
        if (error.status === 429) {
          const detail = error.detail?.detail?.toLowerCase() ?? '';
          throw new Error(
            detail.includes('upload limit')
              ? t.upload.uploadLimitExceeded
              : t.upload.rateLimited,
          );
        }
      }
      throw error;
    }
  }, [
    t.upload.duplicateDocument,
    t.upload.fileTooLarge,
    t.upload.invalidDocument,
    t.upload.rateLimited,
    t.upload.uploadLimitExceeded,
  ]);

  return (
    <ErrorBoundary labels={t.errorBoundary}>
      <div className="app-layout">
        <Header
          title={t.header.title}
          subtitle={t.header.chatSubtitle}
          connected={backendConnected}
        />

        <div
          className={[
            'copilot-layout',
            showInsights ? 'copilot-layout--with-insights' : '',
            historyCollapsed ? 'copilot-layout--history-collapsed' : '',
          ].filter(Boolean).join(' ')}
        >
          <ConversationSidebar
            collapsed={historyCollapsed}
            activeThreadId={threadId}
            activeKind={activeKind}
            sessions={conversationHistory}
            total={conversationHistoryTotal}
            loading={historyLoading}
            clearing={historyClearing}
            clearDisabled={loading || selectingThreadId !== null}
            error={historyError}
            selectingThreadId={selectingThreadId}
            onToggle={() => setHistoryCollapsed((current) => !current)}
            onSelect={onSelectConversation}
            onClear={onClearConversationHistory}
          />

          <main className="main-chat">
            <div className="main-chat__header">
              <h2>{t.chat.title}</h2>
              <span
                className={`status model-status model-status--${runtimeStatusState}`}
                aria-live="polite"
              >
                {runtimeStatus}
              </span>
            </div>

            <ChatWindow
              messages={messages}
              loading={loading}
              demoQuestions={t.chat.demoQuestions}
              onDemoQuestion={handleSend}
            />

            {discoveryStatus && (
              <div className="chat-discovery-status" role="status" aria-live="polite">
                {discoveryStatus}
              </div>
            )}

            <InputBox
              onSubmit={handleSend}
              onFileUpload={handlePdfUpload}
              disabled={loading}
            />
          </main>

          {showInsights && (
            <aside className="agent-panel">
              <AgentTimeline response={response} loading={loading} />
              <CitationList citations={response?.citations ?? []} />
            </aside>
          )}
        </div>
      </div>
    </ErrorBoundary>
  );
}
