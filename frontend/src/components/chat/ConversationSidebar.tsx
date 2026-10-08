import { useLanguage } from '../../i18n/LanguageContext';
import type { ConversationSummary } from '../../types/conversation';
import { Icon } from '../ui/Icon';

interface ConversationSidebarProps {
  collapsed: boolean;
  activeThreadId: string;
  activeKind: 'draft' | 'persisted';
  sessions: ConversationSummary[];
  total: number;
  loading: boolean;
  clearing: boolean;
  clearDisabled: boolean;
  error: string | null;
  selectingThreadId: string | null;
  onToggle: () => void;
  onSelect: (session: ConversationSummary) => void;
  onClear: () => Promise<void>;
}

function formatUpdatedAt(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function ConversationSidebar({
  collapsed,
  activeThreadId,
  activeKind,
  sessions,
  total,
  loading,
  clearing,
  clearDisabled,
  error,
  selectingThreadId,
  onToggle,
  onSelect,
  onClear,
}: ConversationSidebarProps) {
  const { language, t } = useLanguage();
  const locale = language === 'zh-CN' ? 'zh-CN' : 'en-US';
  const clearUnavailable = total === 0
    || loading
    || clearing
    || clearDisabled;

  const handleClear = () => {
    if (
      clearUnavailable
      || !window.confirm(t.chat.historyClearConfirm(total))
    ) {
      return;
    }
    void onClear();
  };

  return (
    <aside
      id="conversation-history"
      className={`conversation-history ${
        collapsed ? 'conversation-history--collapsed' : ''
      }`}
      aria-label={t.chat.historyTitle}
      aria-busy={loading || clearing}
    >
      <div className="conversation-history__header">
        <div className="conversation-history__heading">
          <span className="conversation-history__eyebrow">
            {t.chat.historyTitle}
          </span>
          <span className="conversation-history__count">
            {total}
          </span>
        </div>
        <div className="conversation-history__actions">
          {!collapsed && (
            <button
              type="button"
              className="conversation-history__clear"
              onClick={handleClear}
              disabled={clearUnavailable}
              aria-label={t.chat.historyClear}
              title={t.chat.historyClear}
            >
              {clearing ? t.chat.historyClearing : t.chat.historyClear}
            </button>
          )}
          <button
            type="button"
            className="conversation-history__toggle"
            onClick={onToggle}
            aria-controls="conversation-history"
            aria-expanded={!collapsed}
            aria-label={
              collapsed ? t.chat.historyExpand : t.chat.historyCollapse
            }
            title={collapsed ? t.chat.historyExpand : t.chat.historyCollapse}
          >
            <Icon name={collapsed ? 'chevron-right' : 'chevron-left'} />
          </button>
        </div>
      </div>

      <div className="conversation-history__list">
        {activeKind === 'draft' && (
          <div
            className="conversation-history__item conversation-history__item--active"
            aria-current="true"
            title={t.chat.historyDraft}
          >
            <Icon name="chat" />
            <span className="conversation-history__item-copy">
              <strong>{t.chat.historyDraft}</strong>
              <small>{t.chat.historyDraftHint}</small>
            </span>
          </div>
        )}

        {sessions.map((session) => {
          const active = activeKind === 'persisted'
            && session.threadId === activeThreadId;
          const selecting = selectingThreadId === session.threadId;
          const updatedAt = formatUpdatedAt(session.updatedAt, locale);
          const label = t.chat.historyConversation(updatedAt);

          return (
            <button
              type="button"
              className={`conversation-history__item ${
                active ? 'conversation-history__item--active' : ''
              }`}
              key={session.threadId}
              onClick={() => onSelect(session)}
              aria-current={active ? 'true' : undefined}
              aria-label={`${label}. ${
                t.chat.historyMessageCount(session.messageCount)
              }`}
              title={label}
              disabled={selecting || clearing}
            >
              <Icon name={selecting ? 'clock' : 'chat'} />
              <span className="conversation-history__item-copy">
                <strong>{label}</strong>
                <small>
                  {selecting
                    ? t.chat.historySelecting
                    : t.chat.historyMessageCount(session.messageCount)}
                </small>
              </span>
            </button>
          );
        })}

        {!loading && !error && sessions.length === 0 && activeKind !== 'draft' && (
          <p className="conversation-history__empty">
            {t.chat.historyEmpty}
          </p>
        )}
        {loading && sessions.length === 0 && (
          <p className="conversation-history__empty">
            {t.chat.historyLoading}
          </p>
        )}
        {error && (
          <p className="conversation-history__empty conversation-history__empty--error">
            {error}
          </p>
        )}
      </div>
    </aside>
  );
}
