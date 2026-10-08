import { useLanguage } from '../../i18n/LanguageContext';
import { Icon } from '../ui/Icon';
import type { DocumentDetail } from '../../types/knowledge';

interface DocumentStatsProps {
  document: DocumentDetail;
}

const embeddingStatusIcons: Record<string, string> = {
  completed: '\u2713',
  pending: '\u23F3',
  failed: '\u2717',
};

const vectorStatusIcons: Record<string, string> = {
  stored: '\u2713',
  pending: '\u23F3',
  failed: '\u2717',
};

export function DocumentStats({ document }: DocumentStatsProps) {
  const { t } = useLanguage();

  return (
    <section className="doc-stats" aria-labelledby="doc-stats-title">
      <h2 id="doc-stats-title" className="doc-stats__title">
        {t.document.statistics}
      </h2>

      <div className="doc-stats__grid">
        <div className="doc-stats__card">
          <span className="doc-stats__card-icon" aria-hidden="true">
            <Icon name="clipboard" />
          </span>
          <div className="doc-stats__card-body">
            <span className="doc-stats__card-value">{document.chunkCount}</span>
            <span className="doc-stats__card-label">{t.document.chunks}</span>
          </div>
        </div>

        <div className={`doc-stats__card doc-stats__card--${document.embeddingStatus}`}>
          <span className="doc-stats__card-icon" aria-hidden="true">
            {embeddingStatusIcons[document.embeddingStatus]}
          </span>
          <div className="doc-stats__card-body">
            <span className="doc-stats__card-value doc-stats__card-value--status">
              {t.document.embedding[document.embeddingStatus]}
            </span>
            <span className="doc-stats__card-label">{t.document.embeddingStatus}</span>
          </div>
        </div>

        <div className={`doc-stats__card doc-stats__card--${document.vectorStatus}`}>
          <span className="doc-stats__card-icon" aria-hidden="true">
            {vectorStatusIcons[document.vectorStatus]}
          </span>
          <div className="doc-stats__card-body">
            <span className="doc-stats__card-value doc-stats__card-value--status">
              {t.document.vector[document.vectorStatus]}
            </span>
            <span className="doc-stats__card-label">{t.document.vectorStatus}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
