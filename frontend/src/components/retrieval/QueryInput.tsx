import { useState, useCallback, type FormEvent } from 'react';
import { useLanguage } from '../../i18n/LanguageContext';
import { Icon } from '../ui/Icon';

interface QueryInputProps {
  onSubmit: (query: string) => void;
  loading: boolean;
}

export function QueryInput({ onSubmit, loading }: QueryInputProps) {
  const { t } = useLanguage();
  const [query, setQuery] = useState('');

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      e.preventDefault();
      const trimmed = query.trim();
      if (!trimmed || loading) return;
      onSubmit(trimmed);
    },
    [query, loading, onSubmit],
  );

  return (
    <form className="retrieval-query" onSubmit={handleSubmit}>
      <div className="retrieval-query__input-row">
        <span className="retrieval-query__icon" aria-hidden="true">
          <Icon name="search" />
        </span>
        <input
          type="text"
          className="retrieval-query__input"
          placeholder={t.retrieval.queryPlaceholder}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={loading}
          aria-label={t.retrieval.queryLabel}
        />
        <button
          type="submit"
          className="retrieval-query__button"
          disabled={!query.trim() || loading}
        >
          {loading ? (
            <>
              <span className="retrieval-query__button-spinner" aria-hidden="true" />
              {t.retrieval.searching}
            </>
          ) : (
            <>
              <span className="retrieval-query__button-icon" aria-hidden="true">
                &#x2192;
              </span>
              {t.retrieval.search}
            </>
          )}
        </button>
      </div>
      <p className="retrieval-query__hint">
        {t.retrieval.queryHint}
      </p>
    </form>
  );
}
