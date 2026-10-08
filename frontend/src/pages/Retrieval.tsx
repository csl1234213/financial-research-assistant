import { useState, useCallback } from 'react';
import { Header } from '../components/layout/Header';
import { QueryInput } from '../components/retrieval/QueryInput';
import { RetrievalResult } from '../components/retrieval/RetrievalResult';
import { RetrievalMetricsPanel } from '../components/retrieval/RetrievalMetrics';
import { Icon } from '../components/ui/Icon';
import { queryRetrieval } from '../api/retrieval';
import { useLanguage } from '../i18n/LanguageContext';
import type { RetrievalResponse } from '../types/api';

export function Retrieval() {
  const { t } = useLanguage();
  const [results, setResults] = useState<RetrievalResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleQuery = useCallback(async (query: string) => {
    setLoading(true);
    setError(null);
    setResults(null);
    try {
      const response = await queryRetrieval(query);
      setResults(response);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : t.retrieval.queryFailed;
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [t.retrieval.queryFailed]);

  return (
    <div className="app-layout">
      <Header
        title={t.header.title}
        subtitle={t.header.retrievalSubtitle}
        connected
      />

      <div className="retrieval-layout">
        <div className="retrieval-layout__input">
          <QueryInput onSubmit={handleQuery} loading={loading} />
        </div>

        {error && (
          <div className="retrieval-error" role="alert">
            <span className="retrieval-error__icon" aria-hidden="true">
              &#x26A0;
            </span>
            <span className="retrieval-error__text">{error}</span>
          </div>
        )}

        {loading && (
          <div className="retrieval-skeleton">
            <div className="retrieval-skeleton__metrics">
              <div className="retrieval-skeleton__metric-card" />
              <div className="retrieval-skeleton__metric-card" />
              <div className="retrieval-skeleton__metric-card" />
            </div>
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="retrieval-skeleton__result">
                <div className="retrieval-skeleton__result-header" />
                <div className="retrieval-skeleton__line retrieval-skeleton__line--long" />
                <div className="retrieval-skeleton__line retrieval-skeleton__line--medium" />
                <div className="retrieval-skeleton__line retrieval-skeleton__line--short" />
              </div>
            ))}
          </div>
        )}

        {results && !loading && (
          <div className="retrieval-layout__results">
            <RetrievalMetricsPanel metrics={results.metrics} />

            <section className="retrieval-results-section" aria-labelledby="retrieval-results-title">
              <h2 id="retrieval-results-title" className="retrieval-results-section__title">
                {t.retrieval.resultsTitle}
                <span className="retrieval-results-section__count">
                  {t.retrieval.resultCount(results.chunks.length)}
                </span>
              </h2>

              <div className="retrieval-results-list">
                {results.chunks.map((chunk, idx) => (
                  <RetrievalResult key={idx} chunk={chunk} index={idx} />
                ))}
              </div>
            </section>
          </div>
        )}

        {!results && !loading && !error && (
          <div className="retrieval-empty">
            <span className="retrieval-empty__icon" aria-hidden="true">
              <Icon name="search" />
            </span>
            <p className="retrieval-empty__title">{t.retrieval.emptyTitle}</p>
            <p className="retrieval-empty__hint">
              {t.retrieval.emptyHint}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
