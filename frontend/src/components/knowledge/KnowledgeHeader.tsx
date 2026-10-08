import { useLanguage } from '../../i18n/LanguageContext';

interface KnowledgeHeaderProps {
  documentCount: number;
  indexedCount: number;
  processingCount: number;
  failedCount: number;
  onRefresh: () => void;
  refreshing: boolean;
}

export function KnowledgeHeader({
  documentCount,
  indexedCount,
  processingCount,
  failedCount,
  onRefresh,
  refreshing,
}: KnowledgeHeaderProps) {
  const { t } = useLanguage();

  return (
    <div className="knowledge-header">
      <div className="knowledge-header__titles">
        <div className="knowledge-header__title-row">
          <h1 className="knowledge-header__title">{t.knowledge.title}</h1>
          <button
            type="button"
            className={`knowledge-header__refresh ${refreshing ? 'knowledge-header__refresh--spinning' : ''}`}
            onClick={onRefresh}
            disabled={refreshing}
            title={t.knowledge.refreshTitle}
            aria-label={t.knowledge.refreshTitle}
          >
            <span className="knowledge-header__refresh-icon" aria-hidden="true">
              &#x21BB;
            </span>
            {refreshing ? t.knowledge.refreshing : t.knowledge.refresh}
          </button>
        </div>
        <p className="knowledge-header__subtitle">{t.knowledge.subtitle}</p>
      </div>

      <div className="knowledge-header__stats">
        <div className="knowledge-header__stat">
          <span className="knowledge-header__stat-value">{documentCount}</span>
          <span className="knowledge-header__stat-label">{t.knowledge.total}</span>
        </div>
        <div className="knowledge-header__stat knowledge-header__stat--indexed">
          <span className="knowledge-header__stat-value">{indexedCount}</span>
          <span className="knowledge-header__stat-label">{t.knowledge.indexed}</span>
        </div>
        {processingCount > 0 && (
          <div className="knowledge-header__stat knowledge-header__stat--processing">
            <span className="knowledge-header__stat-value">{processingCount}</span>
            <span className="knowledge-header__stat-label">{t.knowledge.processing}</span>
          </div>
        )}
        {failedCount > 0 && (
          <div className="knowledge-header__stat knowledge-header__stat--failed">
            <span className="knowledge-header__stat-value">{failedCount}</span>
            <span className="knowledge-header__stat-label">{t.knowledge.failed}</span>
          </div>
        )}
      </div>
    </div>
  );
}
