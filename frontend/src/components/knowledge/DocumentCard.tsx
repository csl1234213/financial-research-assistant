import { useLanguage } from '../../i18n/LanguageContext';
import type { DocumentStatus } from '../../types/knowledge';

interface DocumentCardProps {
  filename: string;
  company: string;
  pages: number;
  status: DocumentStatus;
  size?: string;
  uploadedAt: string;
  period?: string;
  chunkCount?: number;
  contentSha256?: string;
  sourceUrl?: string;
  sourceType?: 'sec_edgar' | 'cninfo';
  onDelete?: () => void;
  deleting?: boolean;
}

const statusIcons: Record<DocumentStatus, string> = {
  indexed: '\u2713',
  processing: '\u21BB',
  failed: '\u2717',
  quarantined: '\u2717',
};

function formatDate(iso: string, language: 'en' | 'zh-CN'): string {
  return new Date(iso).toLocaleDateString(language === 'zh-CN' ? 'zh-CN' : 'en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function DocumentCard({
  filename,
  company,
  pages,
  status,
  size,
  uploadedAt,
  period,
  chunkCount,
  contentSha256,
  sourceUrl,
  sourceType,
  onDelete,
  deleting = false,
}: DocumentCardProps) {
  const { language, t } = useLanguage();
  const fileType = filename.split('.').at(-1)?.toUpperCase().slice(0, 4) || 'FILE';

  return (
    <article
      className="doc-card"
    >
      <div className="doc-card__icon">
        <span className="doc-card__icon-text">{fileType}</span>
      </div>

      <div className="doc-card__info">
        <div className="doc-card__header">
          <span className="doc-card__filename">{filename}</span>
          <span className="doc-card__actions">
            <span className={`doc-card__status doc-card__status--${status}`}>
              <span className="doc-card__status-icon" aria-hidden="true">
                {statusIcons[status]}
              </span>
              {t.knowledge.status[status]}
            </span>
            {onDelete && (
              <button
                type="button"
                className="doc-card__delete"
                disabled={deleting || status === 'processing'}
                aria-label={t.knowledge.deleteDocument(filename)}
                title={t.knowledge.deleteDocument(filename)}
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete();
                }}
              >
                {deleting ? t.knowledge.deleting : t.knowledge.delete}
              </button>
            )}
          </span>
        </div>

        <div className="doc-card__meta">
          <span className="doc-card__meta-item">
            <span className="doc-card__meta-label">{t.knowledge.company}</span>
            <span className="doc-card__meta-value">{company}</span>
          </span>
          {period && (
            <>
              <span className="doc-card__meta-divider" />
              <span className="doc-card__meta-item">
                <span className="doc-card__meta-label">{t.knowledge.period}</span>
                <span className="doc-card__meta-value">{period}</span>
              </span>
            </>
          )}
          {chunkCount !== undefined && (
            <>
              <span className="doc-card__meta-divider" />
              <span className="doc-card__meta-item">
                <span className="doc-card__meta-label">{t.knowledge.chunks}</span>
                <span className="doc-card__meta-value">{chunkCount}</span>
              </span>
            </>
          )}
          {pages > 0 && (
            <>
              <span className="doc-card__meta-divider" />
              <span className="doc-card__meta-item">
                <span className="doc-card__meta-label">{t.knowledge.pages}</span>
                <span className="doc-card__meta-value">{pages}</span>
              </span>
            </>
          )}
          {size && (
            <>
              <span className="doc-card__meta-divider" />
              <span className="doc-card__meta-item">
                <span className="doc-card__meta-label">{t.knowledge.size}</span>
                <span className="doc-card__meta-value">{size}</span>
              </span>
            </>
          )}
        </div>

        {uploadedAt && (
          <div className="doc-card__footer">
            <span className="doc-card__date">
              {t.knowledge.uploaded} {formatDate(uploadedAt, language)}
            </span>
          </div>
        )}
        {contentSha256 && (
          <div className="doc-card__checksum" title={contentSha256}>
            {t.knowledge.checksum}: {contentSha256.slice(0, 12)}
          </div>
        )}
        {sourceUrl && (
          <div className="doc-card__source">
            <a
              href={sourceUrl}
              target="_blank"
              rel="noreferrer"
              onClick={(event) => event.stopPropagation()}
            >
              {sourceType === 'cninfo' ? t.knowledge.viewCninfoSource : t.knowledge.viewSource}
            </a>
          </div>
        )}
      </div>
    </article>
  );
}
