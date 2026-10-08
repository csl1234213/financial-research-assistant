import {
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react';
import { Chat } from './pages/Chat';
import { Knowledge } from './pages/Knowledge';
import { DocumentDetail } from './pages/DocumentDetail';
import { Retrieval } from './pages/Retrieval';
import { Settings } from './pages/Settings';
import { AuthPage } from './components/auth/AuthPage';
import { AppShell } from './components/layout/AppShell';
import { getCurrentUser, logoutUser } from './api/auth';
import {
  clearConversationHistory,
  getConversation,
  getConversationHistory,
} from './api/agentSessions';
import { getAccessToken, clearAccessToken } from './api/session';
import { useLanguage } from './i18n/LanguageContext';
import type { ChatMessage } from './types/api';
import type { AuthUser } from './types/auth';
import type {
  ActiveConversation,
  ConversationSummary,
} from './types/conversation';

type Page = 'chat' | 'knowledge' | 'document-detail' | 'retrieval' | 'settings';

interface AppState {
  page: Page;
  documentId?: string;
}

function createDraftConversation(): ActiveConversation {
  return {
    threadId: crypto.randomUUID(),
    kind: 'draft',
    messages: [],
  };
}

function getStateFromHash(): AppState {
  const hash = window.location.hash.replace('#', '');
  if (hash.startsWith('knowledge/document/')) {
    const documentId = hash.replace('knowledge/document/', '');
    if (documentId) {
      return { page: 'document-detail', documentId };
    }
  }
  if (hash === 'knowledge') {
    return { page: 'knowledge' };
  }
  if (hash === 'retrieval') {
    return { page: 'retrieval' };
  }
  if (hash === 'settings') {
    return { page: 'settings' };
  }
  return { page: 'chat' };
}

function App() {
  const { t } = useLanguage();
  const [state, setState] = useState<AppState>(getStateFromHash);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [activeConversation, setActiveConversation] = useState(
    createDraftConversation,
  );
  const [conversationHistory, setConversationHistory] = useState<
    ConversationSummary[]
  >([]);
  const [conversationHistoryTotal, setConversationHistoryTotal] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyClearing, setHistoryClearing] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selectingThreadId, setSelectingThreadId] = useState<string | null>(
    null,
  );
  const conversationRequestId = useRef(0);
  const historyRequestId = useRef(0);
  const currentUserIdRef = useRef<number | null>(user?.id ?? null);
  currentUserIdRef.current = user?.id ?? null;

  const handleHashChange = useCallback(() => {
    setState(getStateFromHash());
  }, []);

  useEffect(() => {
    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [handleHashChange]);

  useEffect(() => {
    let cancelled = false;

    async function restoreSession() {
      if (!getAccessToken()) {
        setCheckingSession(false);
        return;
      }

      try {
        const currentUser = await getCurrentUser();
        if (!cancelled) setUser(currentUser);
      } catch {
        clearAccessToken();
      } finally {
        if (!cancelled) setCheckingSession(false);
      }
    }

    restoreSession();
    return () => {
      cancelled = true;
    };
  }, []);

  const navigateTo = useCallback((target: Page, documentId?: string) => {
    if (target === 'document-detail' && documentId) {
      window.location.hash = `knowledge/document/${documentId}`;
    } else if (target === 'knowledge') {
      window.location.hash = 'knowledge';
    } else if (target === 'retrieval') {
      window.location.hash = 'retrieval';
    } else if (target === 'settings') {
      window.location.hash = 'settings';
    } else {
      window.location.hash = '';
    }
  }, []);

  const refreshConversationHistory = useCallback(async (ownerId: number) => {
    if (currentUserIdRef.current !== ownerId) return;

    const requestId = historyRequestId.current + 1;
    historyRequestId.current = requestId;
    setHistoryLoading(true);
    setHistoryError(null);
    try {
      const history = await getConversationHistory();
      if (
        historyRequestId.current === requestId
        && currentUserIdRef.current === ownerId
      ) {
        setConversationHistory(history.items);
        setConversationHistoryTotal(history.total);
      }
    } catch {
      if (
        historyRequestId.current === requestId
        && currentUserIdRef.current === ownerId
      ) {
        setHistoryError(t.chat.historyLoadError);
      }
    } finally {
      if (
        historyRequestId.current === requestId
        && currentUserIdRef.current === ownerId
      ) {
        setHistoryLoading(false);
      }
    }
  }, [t.chat.historyLoadError]);

  useEffect(() => {
    if (user) {
      void refreshConversationHistory(user.id);
    }
  }, [refreshConversationHistory, user]);

  const handleBackToKnowledge = useCallback(() => {
    window.location.hash = 'knowledge';
  }, []);

  const handleNewChat = useCallback(() => {
    conversationRequestId.current += 1;
    setSelectingThreadId(null);
    setActiveConversation(createDraftConversation());
    navigateTo('chat');
  }, [navigateTo]);

  const handleSelectConversation = useCallback(async (
    session: ConversationSummary,
  ) => {
    if (
      activeConversation.kind === 'persisted'
      && activeConversation.threadId === session.threadId
    ) {
      navigateTo('chat');
      return;
    }

    const requestId = conversationRequestId.current + 1;
    conversationRequestId.current = requestId;
    setSelectingThreadId(session.threadId);
    setHistoryError(null);

    try {
      const detail = await getConversation(
        session.threadId,
        session.messageCount,
      );
      if (conversationRequestId.current !== requestId) return;
      setActiveConversation({
        threadId: session.threadId,
        kind: 'persisted',
        messages: detail.messages,
      });
      navigateTo('chat');
    } catch {
      if (conversationRequestId.current === requestId) {
        setHistoryError(t.chat.historyLoadError);
      }
    } finally {
      if (conversationRequestId.current === requestId) {
        setSelectingThreadId(null);
      }
    }
  }, [
    activeConversation.kind,
    activeConversation.threadId,
    navigateTo,
    t.chat.historyLoadError,
  ]);

  const handleClearConversationHistory = useCallback(async () => {
    const ownerId = currentUserIdRef.current;
    if (!ownerId || historyClearing) return;

    conversationRequestId.current += 1;
    historyRequestId.current += 1;
    setSelectingThreadId(null);
    setHistoryLoading(false);
    setHistoryClearing(true);
    setHistoryError(null);

    try {
      await clearConversationHistory();
      if (currentUserIdRef.current !== ownerId) return;

      setConversationHistory([]);
      setConversationHistoryTotal(0);
      setActiveConversation(createDraftConversation());
      navigateTo('chat');
    } catch {
      if (currentUserIdRef.current !== ownerId) return;

      try {
        const history = await getConversationHistory();
        if (currentUserIdRef.current === ownerId) {
          setConversationHistory(history.items);
          setConversationHistoryTotal(history.total);
          setActiveConversation((current) => {
            const currentStillExists = current.kind === 'persisted'
              && history.items.some(
                (session) => session.threadId === current.threadId,
              );
            return current.kind === 'persisted' && !currentStillExists
              ? createDraftConversation()
              : current;
          });
        }
      } catch {
        // Preserve the last known list when the recovery refresh also fails.
      }

      if (currentUserIdRef.current === ownerId) {
        setHistoryError(t.chat.historyClearError);
      }
    } finally {
      if (currentUserIdRef.current === ownerId) {
        setHistoryClearing(false);
      }
    }
  }, [historyClearing, navigateTo, t.chat.historyClearError]);

  const handleConversationMessagesChange = useCallback((
    threadId: string,
    messages: ChatMessage[],
  ) => {
    setActiveConversation((current) => (
      current.threadId === threadId
        ? { ...current, messages }
        : current
    ));
  }, []);

  const handleTurnCompleted = useCallback((threadId: string) => {
    setActiveConversation((current) => (
      current.threadId === threadId
        ? { ...current, kind: 'persisted' }
        : current
    ));
    const ownerId = currentUserIdRef.current;
    if (ownerId) {
      void refreshConversationHistory(ownerId);
    }
  }, [refreshConversationHistory]);

  const handleLogout = useCallback(() => {
    conversationRequestId.current += 1;
    historyRequestId.current += 1;
    currentUserIdRef.current = null;
    logoutUser();
    setUser(null);
    setConversationHistory([]);
    setConversationHistoryTotal(0);
    setHistoryLoading(false);
    setHistoryClearing(false);
    setHistoryError(null);
    setActiveConversation(createDraftConversation());
    window.location.hash = '';
  }, []);

  if (checkingSession) {
    return <main className="auth-loading">{t.app.restoringSession}</main>;
  }

  if (!user) {
    return <AuthPage onAuthenticated={setUser} />;
  }

  const currentNavigationPage = state.page === 'document-detail'
    ? 'knowledge'
    : state.page;

  return (
    <AppShell
      currentPage={currentNavigationPage}
      email={user.email}
      onNavigate={navigateTo}
      onNewChat={handleNewChat}
      onLogout={handleLogout}
    >
      {state.page === 'chat' && (
        <Chat
          key={activeConversation.threadId}
          threadId={activeConversation.threadId}
          initialMessages={activeConversation.messages}
          activeKind={activeConversation.kind}
          conversationHistory={conversationHistory}
          conversationHistoryTotal={conversationHistoryTotal}
          historyLoading={historyLoading}
          historyClearing={historyClearing}
          historyError={historyError}
          selectingThreadId={selectingThreadId}
          onSelectConversation={handleSelectConversation}
          onClearConversationHistory={handleClearConversationHistory}
          onMessagesChange={handleConversationMessagesChange}
          onTurnCompleted={handleTurnCompleted}
        />
      )}
      {state.page === 'knowledge' && <Knowledge key={`${user.tenant?.id}:${user.id}`} user={user} />}
      {state.page === 'document-detail' && state.documentId && (
        <DocumentDetail documentId={state.documentId} onBack={handleBackToKnowledge} />
      )}
      {state.page === 'retrieval' && <Retrieval />}
      {state.page === 'settings' && <Settings />}
    </AppShell>
  );
}

export default App;
