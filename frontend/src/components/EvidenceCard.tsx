import type { Citation } from '../types/chat';

interface EvidenceCardProps {
  citation: Citation;
  labels: {
    chunk: string;
    snippet: string;
    similarity: (score: number) => string;
  };
}

export function EvidenceCard({ citation, labels }: EvidenceCardProps) {
  return (
    <article className="evidence-card">
      <div className="evidence-card__header">
        <strong>{citation.source}</strong>
        <span>
          {citation.similarity === null
            ? 'N/A'
            : labels.similarity(citation.similarity)}
        </span>
      </div>
      <dl className="evidence-card__metadata">
        <div>
          <dt>{labels.chunk}</dt>
          <dd>{citation.chunk_id}</dd>
        </div>
      </dl>
      <p>
        <span className="evidence-card__snippet-label">{labels.snippet}</span>
        {citation.preview}
      </p>
    </article>
  );
}
