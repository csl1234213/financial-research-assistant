import type { ChatMessage } from '../types/chat';
import { SafeMarkdown } from './chat/SafeMarkdown';

interface ChatWindowProps {
  messages: ChatMessage[];
  loading: boolean;
  labels: {
    conversation: string;
    user: string;
    assistant: string;
    emptyState: string;
    loading: string;
  };
}

export function ChatWindow({ messages, loading, labels }: ChatWindowProps) {
  const isEmpty = messages.length === 0;

  return (
    <section className="chat-window" aria-label={labels.conversation} aria-live="polite">
      {isEmpty && !loading && <p className="chat-empty-state">{labels.emptyState}</p>}

      {messages.map((message) => (
        <article className={`message message--${message.role}`} key={message.id}>
          <span className="message__role">
            {message.role === 'user' ? labels.user : labels.assistant}
          </span>
          {message.role === 'assistant'
            ? <SafeMarkdown content={message.content} />
            : <p>{message.content}</p>}
        </article>
      ))}

      {loading && (
        <article className="message message--assistant message--loading" aria-busy="true">
          <span className="message__role">{labels.assistant}</span>
          <p>{labels.loading}</p>
        </article>
      )}
    </section>
  );
}
