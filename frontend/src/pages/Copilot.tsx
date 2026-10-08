import { useEffect, useState } from 'react';
import { sendChatMessage } from '../api/chat';
import { AgentTrace } from '../components/AgentTrace';
import { ChatInput } from '../components/ChatInput';
import { ChatWindow } from '../components/ChatWindow';
import { EvidenceCard } from '../components/EvidenceCard';
import { Sidebar } from '../components/Sidebar';
import type { ChatMessage, ChatResponse } from '../types/chat';
import type { Language } from '../types/language';

const copy = {
  en: {
    documentTitle: 'Financial AI Copilot',
    sidebar: {
      runtime: 'Financial Agent Runtime',
      title: 'AI Copilot',
      demoCompanies: 'Demo companies',
      language: 'Language',
    },
    chat: {
      areaLabel: 'Financial AI Copilot',
      localDemo: 'Local demo',
      title: 'Financial AI Copilot',
      mockData: 'Mock data',
      conversation: 'Conversation',
      user: 'You',
      assistant: 'Copilot',
      inputLabel: 'Ask a financial question',
      placeholder: 'Ask about a company or filing...',
      submitLabel: 'Send',
      emptyState: 'Ask about Tesla, NVIDIA, or Apple financial performance',
      loading: 'Agent Runtime is analyzing...',
    },
    trace: {
      title: 'Agent Trace',
      empty: 'Submit a question to view the agent trace.',
      reasoning: 'Reasoning',
      intent: 'Intent',
      companies: 'Companies',
      researchMode: 'Research mode',
      execution: 'Execution',
      strategy: 'Strategy',
      provider: 'Provider',
      workflow: 'Workflow',
      type: 'Type',
      status: 'Status',
    },
    evidence: {
      title: 'Evidence',
      empty: 'Evidence will appear after analysis.',
      chunk: 'Chunk',
      snippet: 'Snippet: ',
      similarity: (score: number) => `${(score * 100).toFixed(1)}% match`,
    },
  },
  'zh-CN': {
    documentTitle: '金融 AI Copilot',
    sidebar: {
      runtime: '金融智能体运行平台',
      title: 'AI Copilot',
      demoCompanies: '演示公司',
      language: '语言',
    },
    chat: {
      areaLabel: '金融 AI Copilot',
      localDemo: '本地演示',
      title: '金融 AI Copilot',
      mockData: '模拟数据',
      conversation: '对话',
      user: '你',
      assistant: 'Copilot',
      inputLabel: '提出财务问题',
      placeholder: '询问公司或财报信息…',
      submitLabel: '发送',
      emptyState: '询问特斯拉、英伟达或苹果的财务表现',
      loading: '智能体运行平台正在分析…',
    },
    trace: {
      title: '智能体轨迹',
      empty: '提交问题后将在此显示智能体轨迹。',
      reasoning: '推理',
      intent: '意图',
      companies: '公司',
      researchMode: '研究模式',
      execution: '执行',
      strategy: '执行策略',
      provider: '服务提供方',
      workflow: '工作流',
      type: '类型',
      status: '状态',
    },
    evidence: {
      title: '证据',
      empty: '分析完成后将在此显示证据。',
      chunk: '分块',
      snippet: '片段：',
      similarity: (score: number) => `匹配度 ${(score * 100).toFixed(1)}%`,
    },
  },
};

export function Copilot() {
  const [language, setLanguage] = useState<Language>('en');
  const [threadId] = useState(() => crypto.randomUUID());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [currentResponse, setCurrentResponse] = useState<ChatResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const labels = copy[language];

  useEffect(() => {
    document.documentElement.lang = language;
    document.title = labels.documentTitle;
  }, [language, labels.documentTitle]);

  async function handleSend(message: string) {
    const submittedAt = Date.now();
    const assistantId = `assistant-${submittedAt}`;
    let streamedContent = '';

    setMessages((currentMessages) => [
      ...currentMessages,
      { id: `user-${submittedAt}`, role: 'user', content: message },
    ]);
    setCurrentResponse(null);
    setLoading(true);

    try {
      const response = await sendChatMessage(
        message,
        undefined,
        threadId,
        language,
        (delta) => {
          streamedContent += delta;
          setMessages((currentMessages) => {
            const existingIndex = currentMessages.findIndex(
              (item) => item.id === assistantId,
            );
            const streamedMessage: ChatMessage = {
              id: assistantId,
              role: 'assistant',
              content: streamedContent,
            };
            if (existingIndex < 0) return [...currentMessages, streamedMessage];
            return currentMessages.map((item, index) => (
              index === existingIndex ? streamedMessage : item
            ));
          });
        },
      );

      setCurrentResponse(response);
      setMessages((currentMessages) => {
        const finalMessage: ChatMessage = {
          id: assistantId,
          role: 'assistant',
          content: response.report,
          response,
        };
        if (!currentMessages.some((item) => item.id === assistantId)) {
          return [...currentMessages, finalMessage];
        }
        return currentMessages.map((item) => (
          item.id === assistantId ? finalMessage : item
        ));
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="copilot-layout">
      <Sidebar language={language} onLanguageChange={setLanguage} labels={labels.sidebar} />

      <section className="main-chat" aria-label={labels.chat.areaLabel}>
        <header className="main-chat__header">
          <div>
            <p className="eyebrow">{labels.chat.localDemo}</p>
            <h2>{labels.chat.title}</h2>
          </div>
          <span className="status">{labels.chat.mockData}</span>
        </header>
        <ChatWindow messages={messages} loading={loading} labels={labels.chat} />
        <ChatInput
          onSubmit={handleSend}
          inputLabel={labels.chat.inputLabel}
          placeholder={labels.chat.placeholder}
          submitLabel={labels.chat.submitLabel}
          disabled={loading}
        />
      </section>

      <aside className="insight-panels">
        <AgentTrace response={currentResponse} labels={labels.trace} />
        <section className="panel" aria-labelledby="evidence-title">
          <h2 id="evidence-title">{labels.evidence.title}</h2>
          {currentResponse ? (
            <div className="evidence-list">
              {currentResponse.citations.map((citation) => (
                <EvidenceCard
                  citation={citation}
                  key={`${citation.source}-${citation.chunk_id}`}
                  labels={labels.evidence}
                />
              ))}
            </div>
          ) : (
            <p className="panel__empty">{labels.evidence.empty}</p>
          )}
        </section>
      </aside>
    </main>
  );
}
