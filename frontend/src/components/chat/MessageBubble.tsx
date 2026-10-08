import { useLanguage } from '../../i18n/LanguageContext';
import { AssistantReport } from './AssistantReport';
import { formatGenerationDuration } from './generationDuration';
import { Icon } from '../ui/Icon';
import type { ChatResponse } from '../../types/api';

interface MessageBubbleProps {
  financialPresentation?: ChatResponse['financialPresentation'];
  savedCitations?: ChatResponse['citations'];
  role: 'user' | 'assistant';
  content: string;
  response?: ChatResponse;
  citationNamespace?: string;
  loading?: boolean;
  loadingText?: string;
  durationMs?: number;
  streaming?: boolean;
}

export function MessageBubble({
  role,
  content,
  response,
  citationNamespace,
  loading = false,
  loadingText,
  durationMs,
  streaming = false,
  financialPresentation,
  savedCitations,
}: MessageBubbleProps) {
  const { t, language } = useLanguage();
  const roleLabel = role === 'user' ? t.chat.user : t.chat.assistant;
  const generationDuration = formatGenerationDuration(durationMs, language);

  if (loading) {
    return (
      <article className="message message--assistant message--loading" aria-busy="true">
        <div className="message__header">
          <div className="message__avatar" aria-hidden="true">
            <Icon name="financial-research" />
          </div>
          <span className="message__role">{t.chat.assistant}</span>
        </div>
        <div className="message__body">
          <div className="message__loading-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          {loadingText ?? t.chat.loading}
        </div>
      </article>
    );
  }

  return (
    <article
      className={`message message--${role}${streaming ? ' message--streaming' : ''}`}
      aria-busy={streaming || undefined}
    >
      <div className="message__header">
        <div className="message__avatar" aria-hidden="true">
          {role === 'user' ? 'U' : <Icon name="financial-research" />}
        </div>
        <span className="message__role">
          {roleLabel}
        </span>
        {role === 'assistant' && generationDuration !== null && (
          <span className="message__time">
            <Icon name="clock" />
            {generationDuration}
          </span>
        )}
      </div>
      <div className="message__body">
        {role === 'assistant'
          ? (
            <AssistantReport
              content={content}
              response={response}
              financialPresentation={financialPresentation}
              savedCitations={savedCitations}
              citationNamespace={citationNamespace}
            />
          )
          : <p>{content}</p>}
      </div>
    </article>
  );
}
