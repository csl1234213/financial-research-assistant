import type { RetrievalChunk } from '../../types/api';
import { useLanguage } from '../../i18n/LanguageContext';

interface RetrievalResultProps {
  chunk: RetrievalChunk;
  index: number;
}

function formatScore(score: number): string {
  return (score * 100).toFixed(1) + '%';
}

function getScoreLevel(score: number): string {
  if (score >= 0.85) return 'high';
  if (score >= 0.65) return 'medium';
  return 'low';
}

export function RetrievalResult({ chunk, index }: RetrievalResultProps) {
  const { t } = useLanguage();
  const scoreLevel = getScoreLevel(chunk.score);

  return (
    <article className="retrieval-result">
      <div className="retrieval-result__header">
        <span className="retrieval-result__rank">#{index + 1}</span>
        <span className="retrieval-result__filename">{chunk.filename}</span>
        <span className="retrieval-result__page">{t.retrieval.page} {chunk.page}</span>
        <span className={`retrieval-result__score retrieval-result__score--${scoreLevel}`}>
          {formatScore(chunk.score)}
        </span>
      </div>

      <p className="retrieval-result__content">{chunk.content}</p>

      <div className="retrieval-result__footer">
        <span className="retrieval-result__meta">
          <span className="retrieval-result__meta-label">{t.retrieval.source}</span>
          <span className="retrieval-result__meta-value">{chunk.filename}</span>
        </span>
        <span className="retrieval-result__meta-divider" />
        <span className="retrieval-result__meta">
          <span className="retrieval-result__meta-label">{t.retrieval.page}</span>
          <span className="retrieval-result__meta-value">{chunk.page}</span>
        </span>
        <span className="retrieval-result__meta-divider" />
        <span className="retrieval-result__meta">
          <span className="retrieval-result__meta-label">{t.retrieval.similarity}</span>
          <span className="retrieval-result__meta-value retrieval-result__meta-value--score">
            {chunk.score.toFixed(4)}
          </span>
        </span>
      </div>
    </article>
  );
}
