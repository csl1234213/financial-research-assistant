import { useLanguage } from '../../i18n/LanguageContext';
import type { DocumentChunk } from '../../types/knowledge';

interface ChunkCardProps {
  chunk: DocumentChunk;
}

function formatScore(score: number): string {
  return (score * 100).toFixed(1) + '%';
}

function getScoreColor(score: number): string {
  if (score >= 0.9) return 'high';
  if (score >= 0.7) return 'medium';
  return 'low';
}

export function ChunkCard({ chunk }: ChunkCardProps) {
  const { t } = useLanguage();
  const scoreLevel = chunk.score !== undefined ? getScoreColor(chunk.score) : undefined;
  const metadataEntries = Object.entries(chunk.metadata);

  return (
    <article className="chunk-card">
      <div className="chunk-card__header">
        <span className="chunk-card__index">{t.document.chunk(chunk.index)}</span>
        {chunk.score !== undefined && (
          <span className={`chunk-card__score chunk-card__score--${scoreLevel}`}>
            {formatScore(chunk.score)}
          </span>
        )}
      </div>

      <p className="chunk-card__content">{chunk.content}</p>

      {metadataEntries.length > 0 && (
        <div className="chunk-card__metadata">
          {metadataEntries.map(([key, value]) => (
            <span key={key} className="chunk-card__metadata-item">
              <span className="chunk-card__metadata-key">{key}</span>
              <span className="chunk-card__metadata-value">{value}</span>
            </span>
          ))}
        </div>
      )}
    </article>
  );
}
