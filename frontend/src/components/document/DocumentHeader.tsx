import { useLanguage } from '../../i18n/LanguageContext';
import type { DocumentDetail } from '../../types/knowledge';

interface DocumentHeaderProps {
  document: DocumentDetail;
  onBack: () => void;
}

const statusIcons: Record<string, string> = {
  indexed: '\u2713',
  processing: '\u21BB',
  failed: '\u2717',
};

function formatDate(iso: string, language: 'en' | 'zh-CN'): string {
  return new Date(iso).toLocaleDateString(language === 'zh-CN' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function DocumentHeader({ document, onBack }: DocumentHeaderProps) {
  const { language, t } = useLanguage();

  return (
    <header className="doc-detail-header">
      <button
        type="button"
        className="doc-detail-header__back"
        onClick={onBack}
        aria-label={t.document.backToKnowledge}
      >
        <span className="doc-detail-header__back-icon" aria-hidden="true">
          &#8592;
        </span>
        {t.document.backToDocuments}
      </button>

      <div className="doc-detail-header__main">
        <div className="doc-detail-header__icon">
          <span className="doc-detail-header__icon-text">PDF</span>
        </div>

        <div className="doc-detail-header__info">
          <h1 className="doc-detail-header__filename">{document.filename}</h1>

          <div className="doc-detail-header__meta">
            <span className="doc-detail-header__meta-item">
              <span className="doc-detail-header__meta-label">{t.document.company}</span>
              <span className="doc-detail-header__meta-value">{document.company}</span>
            </span>
            <span className="doc-detail-header__meta-divider" />
            <span className="doc-detail-header__meta-item">
              <span className="doc-detail-header__meta-label">{t.document.pages}</span>
              <span className="doc-detail-header__meta-value">{document.pages}</span>
            </span>
            <span className="doc-detail-header__meta-divider" />
            <span className="doc-detail-header__meta-item">
              <span className="doc-detail-header__meta-label">{t.document.statusLabel}</span>
              <span className={`doc-detail-header__status doc-detail-header__status--${document.status}`}>
                <span className="doc-detail-header__status-icon" aria-hidden="true">
                  {statusIcons[document.status]}
                </span>
                {t.document.status[document.status]}
              </span>
            </span>
            {document.size && (
              <>
                <span className="doc-detail-header__meta-divider" />
                <span className="doc-detail-header__meta-item">
                  <span className="doc-detail-header__meta-label">{t.document.size}</span>
                  <span className="doc-detail-header__meta-value">{document.size}</span>
                </span>
              </>
            )}
          </div>

          <div className="doc-detail-header__date">
            {t.document.uploaded} {formatDate(document.uploadedAt, language)}
          </div>
        </div>
      </div>
    </header>
  );
}
