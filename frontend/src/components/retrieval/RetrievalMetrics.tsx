import type { RetrievalMetrics } from '../../types/api';
import { useLanguage } from '../../i18n/LanguageContext';
import { Icon } from '../ui/Icon';

interface RetrievalMetricsProps {
  metrics: RetrievalMetrics;
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function RetrievalMetricsPanel({ metrics }: RetrievalMetricsProps) {
  const { t } = useLanguage();

  return (
    <section className="retrieval-metrics" aria-labelledby="retrieval-metrics-title">
      <h2 id="retrieval-metrics-title" className="retrieval-metrics__title">
        {t.retrieval.metricsTitle}
      </h2>

      <div className="retrieval-metrics__grid">
        <div className="retrieval-metrics__card">
          <span className="retrieval-metrics__card-icon" aria-hidden="true">
            <Icon name="clock" />
          </span>
          <div className="retrieval-metrics__card-body">
            <span className="retrieval-metrics__card-value">
              {formatLatency(metrics.latencyMs)}
            </span>
            <span className="retrieval-metrics__card-label">{t.retrieval.latency}</span>
          </div>
        </div>

        <div className="retrieval-metrics__card">
          <span className="retrieval-metrics__card-icon" aria-hidden="true">
            <Icon name="clipboard" />
          </span>
          <div className="retrieval-metrics__card-body">
            <span className="retrieval-metrics__card-value">{metrics.chunkCount}</span>
            <span className="retrieval-metrics__card-label">{t.retrieval.chunksRetrieved}</span>
          </div>
        </div>

        <div className="retrieval-metrics__card">
          <span className="retrieval-metrics__card-icon" aria-hidden="true">
            <Icon name="sliders" />
          </span>
          <div className="retrieval-metrics__card-body">
            <span className="retrieval-metrics__card-value retrieval-metrics__card-value--type">
              {metrics.retrieverType}
            </span>
            <span className="retrieval-metrics__card-label">{t.retrieval.retrieverType}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
