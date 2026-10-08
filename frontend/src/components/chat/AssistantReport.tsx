import { useState } from 'react';
import { fetchSourceDocument } from '../../api/sourceDocuments';
import { useLanguage } from '../../i18n/LanguageContext';
import type { ChatResponse, Citation } from '../../types/api';
import { SafeMarkdown } from './SafeMarkdown';
import {
  buildCitationDomId,
  localizeCnyAmounts,
  shouldShowAnswerDisclaimer,
  splitResearchReport,
} from './reportPresentation';

interface AssistantReportProps {
  financialPresentation?: ChatResponse['financialPresentation'];
  savedCitations?: Citation[];
  content: string;
  response?: ChatResponse;
  citationNamespace?: string;
}

interface DetailField {
  label: string;
  value: string;
}

function CompactCitationTargets({
  citations,
  citationNamespace,
  label,
  evidenceLabel,
}: {
  citations: Citation[];
  citationNamespace?: string;
  label: string;
  evidenceLabel: (index: number) => string;
}) {
  const [sourceError, setSourceError] = useState('');
  async function openSource(citation: Citation) {
    // Create the viewer synchronously to preserve the user's popup gesture.
    const viewer = window.open('about:blank', '_blank');
    if (!viewer) { setSourceError('Please allow the source viewer window.'); return; }
    viewer.opener = null;
    try {
      setSourceError('');
      const blob = await fetchSourceDocument(citation.document_id!, citation.content_sha256!, citation.page!);
      const url = URL.createObjectURL(blob);
      viewer.location.replace(`${url}#page=${citation.page}`);
      // Keep the blob alive while the PDF viewer uses it, then release it.
      const timer = window.setInterval(() => {
        if (viewer.closed) { URL.revokeObjectURL(url); window.clearInterval(timer); }
      }, 1000);
    } catch (failure: unknown) {
      viewer.close();
      setSourceError(failure instanceof Error ? failure.message : 'Source unavailable.');
    }
  }
  if (!citationNamespace || citations.length === 0) return null;

  return (
    <nav className="assistant-report__sources" aria-label={label}>
      <span className="assistant-report__sources-label">{label}</span>
      <div className="assistant-report__source-list">
        {citations.map((citation) => {
          const evidenceNumber = citation.rank;
          const similarity = citation.similarity === null
            ? null
            : `${(citation.similarity * 100).toFixed(1)}%`;

          return (
            <span
              id={buildCitationDomId(citationNamespace, evidenceNumber)}
              className="assistant-report__source-chip"
              title={`${citation.source} — ${citation.preview}`}
              aria-label={`${evidenceLabel(evidenceNumber)}: ${citation.source}`}
              key={`${citation.source}-${citation.chunk_id}-${evidenceNumber}`}
              tabIndex={-1}
            >
              <span className="assistant-report__source-rank">
                [{evidenceNumber}]
              </span>
              <span className="assistant-report__source-name">
                {citation.source}
              </span>
              {similarity && (
                <span className="assistant-report__source-score">
                  {similarity}
                </span>
              )}
              {citation.document_id && citation.content_sha256 && citation.page && citation.page > 0 && (
                <button type="button" onClick={() => { void openSource(citation); }}
                  aria-label={`${citation.source}, page ${citation.page}`}>
                  PDF · {citation.page}
                </button>
              )}
            </span>
          );
        })}
      </div>
      {sourceError && <span role="alert">{sourceError}</span>}
    </nav>
  );
}

export function AssistantReport({
  content,
  response,
  citationNamespace,
  financialPresentation,
  savedCitations,
}: AssistantReportProps) {
  const { language, t } = useLanguage();
  const report = splitResearchReport(content);
  const answerContent = (response?.financialPresentation ?? financialPresentation)?.rendered[language]
    ?? localizeCnyAmounts(report?.modelAnswer ?? content, language);
  const showDisclaimer = shouldShowAnswerDisclaimer(response?.report ?? content);
  const citations = response?.citations ?? savedCitations ?? [];
  const markdownProps = {
    citationNamespace,
    citationCount: citations.length,
  };
  const routingModel = response?.routing?.model;
  const detailFields: DetailField[] = response
    ? [
        { label: t.chat.intent, value: response.reasoning.intent },
        {
          label: t.chat.companies,
          value: response.reasoning.companies.join(', ') || t.agent.notAvailable,
        },
        { label: t.chat.researchMode, value: response.reasoning.research_mode },
        {
          label: t.chat.workflow,
          value: response.workflow?.type ?? t.agent.notAvailable,
        },
        {
          label: t.chat.strategy,
          value: response.execution?.strategy ?? t.agent.notAvailable,
        },
        {
          label: t.chat.provider,
          value: response.routing?.provider ?? t.agent.notAvailable,
        },
        {
          label: t.chat.model,
          value: typeof routingModel === 'string' && routingModel
            ? routingModel
            : t.agent.notAvailable,
        },
        {
          label: t.chat.executionTime,
          value: `${response.execution_time.toFixed(2)}s`,
        },
      ]
    : [];
  const hasDetails = Boolean(
    report?.question
    || report?.evidenceUsed
    || report?.agentAnalysis
    || detailFields.length,
  );

  return (
    <div className="assistant-report">
      <section
        className="assistant-report__answer"
        aria-label={t.chat.modelAnswer}
      >
        <SafeMarkdown content={answerContent} {...markdownProps} />
        {showDisclaimer && (
          <p className="assistant-report__disclaimer" role="note">
            {t.chat.answerDisclaimer}
          </p>
        )}
      </section>

      <CompactCitationTargets
        citations={citations}
        citationNamespace={citationNamespace}
        label={t.chat.evidenceSources}
        evidenceLabel={t.chat.evidenceReference}
      />

      {hasDetails && (
        <details className="assistant-report__section assistant-report__section--agent">
          <summary>{t.chat.analysisDetails}</summary>

          <div className="assistant-report">
            {report?.question && (
              <section
                className="assistant-report__question"
                aria-label={t.chat.reportQuestion}
              >
                <span className="assistant-report__section-label">
                  {t.chat.reportQuestion}
                </span>
                <SafeMarkdown content={report.question} {...markdownProps} />
              </section>
            )}

            {report?.agentAnalysis && (
              <section>
                <div className="assistant-report__section-heading">
                  <span className="assistant-report__badge assistant-report__badge--agent">
                    Agent
                  </span>
                  <div>
                    <h3>{t.chat.agentEvidenceAnalysis}</h3>
                    <p>{t.chat.agentEvidenceDescription}</p>
                  </div>
                </div>
                <SafeMarkdown content={report.agentAnalysis} {...markdownProps} />
              </section>
            )}

            {report?.evidenceUsed && (
              <section className="assistant-report__question">
                <span className="assistant-report__section-label">
                  {t.chat.evidenceUsed}
                </span>
                <SafeMarkdown content={report.evidenceUsed} {...markdownProps} />
              </section>
            )}

            {detailFields.length > 0 && (
              <section className="assistant-report__question">
                <span className="assistant-report__section-label">
                  {t.chat.reasoningDetails}
                </span>
                <dl>
                  {detailFields.map((field) => (
                    <div key={field.label}>
                      <dt>{field.label}</dt>
                      <dd>{field.value}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
          </div>
        </details>
      )}
    </div>
  );
}
