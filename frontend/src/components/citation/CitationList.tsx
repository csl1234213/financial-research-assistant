import { useEffect, useState } from 'react';
import { CitationCard } from './CitationCard';
import { hashTargetsCitationRank } from './citationTarget';
import { useLanguage } from '../../i18n/LanguageContext';
import type { Citation } from '../../types/chat';

interface CitationListProps {
  citations: Citation[];
  title?: string;
  emptyMessage?: string;
}

export function CitationList({
  citations,
  title,
  emptyMessage,
}: CitationListProps) {
  const { t } = useLanguage();
  const hasCitations = citations.length > 0;
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function hashTargetsCitation() {
      return citations.some(
        (citation) => hashTargetsCitationRank(window.location.hash, citation.rank),
      );
    }

    setOpen(hashTargetsCitation());

    function handleHashChange() {
      if (hashTargetsCitation()) {
        setOpen(true);
      }
    }

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, [citations]);

  return (
    <>
      {!hasCitations ? (
        <section
          className="citation-list-panel"
          aria-labelledby="citation-list-title"
        >
          <h2 id="citation-list-title" className="citation-list-panel__title">
            {title ?? t.citations.title}
          </h2>
          <p className="citation-list-panel__empty">
            {emptyMessage ?? t.citations.empty}
          </p>
        </section>
      ) : (
        <details
          className="citation-list-panel"
          open={open}
          onToggle={(event) => setOpen(event.currentTarget.open)}
          aria-labelledby="citation-list-title"
        >
          <summary>
            <span className="citation-list-panel__header">
              <span
                id="citation-list-title"
                className="citation-list-panel__title"
              >
                {title ?? t.citations.title}
              </span>
              <span className="citation-list-panel__count">
                {t.citations.sourceCount(citations.length)}
              </span>
            </span>
          </summary>

          <div className="citation-list citation-list--disclosed">
            {citations.map((citation, index) => (
              <CitationCard
                key={`${citation.rank}-${citation.source}-${citation.chunk_id}-${index}`}
                citation={citation}
              />
            ))}
          </div>
        </details>
      )}
    </>
  );
}
