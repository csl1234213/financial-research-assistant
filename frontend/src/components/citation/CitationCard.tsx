import { useEffect, useRef, useState } from 'react';
import { SourceBadge } from './SourceBadge';
import {
  getCitationTargetId,
  hashTargetsCitationRank,
} from './citationTarget';
import { useLanguage } from '../../i18n/LanguageContext';
import type { Citation } from '../../types/chat';

interface CitationCardProps {
  citation: Citation;
}

export function CitationCard({ citation }: CitationCardProps) {
  const { t } = useLanguage();
  const [expanded, setExpanded] = useState(false);
  const [targeted, setTargeted] = useState(false);
  const cardRef = useRef<HTMLElement>(null);
  const cardId = getCitationTargetId(citation.rank);
  const sourceLabelId = `${cardId}-source`;
  const contextId = `${cardId}-context`;

  const sourceName = citation.source.replace(/\.(pdf|xlsx|docx|csv)$/i, '')
    || t.citations.sourceFallback(citation.rank);
  const snippet = citation.preview;
  const sourceLocation = citation.source_locator
    || citation.page_label
    || (citation.page ? `Page ${citation.page}` : `Chunk ${citation.chunk_id}`);

  useEffect(() => {
    function syncTarget() {
      const isTarget = hashTargetsCitationRank(
        window.location.hash,
        citation.rank,
      );
      setTargeted(isTarget);

      if (isTarget) {
        setExpanded(true);
        window.requestAnimationFrame(() => {
          cardRef.current?.focus();
        });
      }
    }

    syncTarget();
    window.addEventListener('hashchange', syncTarget);
    return () => window.removeEventListener('hashchange', syncTarget);
  }, [citation.rank]);

  return (
    <article
      ref={cardRef}
      id={cardId}
      className="citation-card"
      tabIndex={-1}
      aria-current={targeted ? 'location' : undefined}
      aria-labelledby={sourceLabelId}
      data-evidence-rank={citation.rank}
      data-highlighted={targeted ? 'true' : undefined}
    >
      <div className="citation-card__header">
        <div className="citation-card__source-info">
          <span className="citation-card__index">[{citation.rank}]</span>
          <span id={sourceLabelId} className="citation-card__source-name">
            {sourceName}
          </span>
          {sourceLocation && (
            <span className="citation-card__page" title={sourceLocation}>{sourceLocation}</span>
          )}
        </div>
        <SourceBadge similarity={citation.similarity} />
      </div>

      <div
        id={contextId}
        className={`citation-card__body ${expanded ? 'citation-card__body--expanded' : ''}`}
      >
        <p className="citation-card__snippet">{snippet}</p>
      </div>

      <div className="citation-card__footer">
        <span className="citation-card__meta">
          <span className="citation-card__meta-label">{t.citations.source}</span>
          <span className="citation-card__meta-value">{citation.source}</span>
        </span>
        <button
          type="button"
          className="citation-card__expand"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-controls={contextId}
        >
          {expanded ? t.citations.collapse : t.citations.viewContext}
        </button>
      </div>
    </article>
  );
}
