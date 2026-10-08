import { useEffect, useState } from 'react';
import { AgentStep } from './AgentStep';
import type { AgentStepData } from './AgentStep';
import { useLanguage } from '../../i18n/LanguageContext';
import type { Translation } from '../../i18n/translations';
import type { ChatResponse } from '../../types/api';
import { getRuntimeFailureKind } from '../chat/reportPresentation';
import { isCompletedStructuredFact, isSafeStructuredRefusal } from './structuredExecution';

interface AgentTimelineProps {
  response: ChatResponse | null;
  loading: boolean;
  title?: string;
  emptyMessage?: string;
}

function buildTimeline(
  response: ChatResponse | null,
  loading: boolean,
  labels: Translation['agent'],
): AgentStepData[] {
  if (response) {
    if (isSafeStructuredRefusal(response)) {
      return [{ id: 'structured-refusal', name: labels.structuredFact,
        description: response.report, status: 'safe_refusal' }];
    }
    if (isCompletedStructuredFact(response) && getRuntimeFailureKind(response.report) === null) {
      return [{
        id: 'structured-fact', name: labels.structuredFact,
        description: labels.structuredFactCompleted, status: 'completed',
      }];
    }
    const hasExecutionContract = Boolean(
      response.execution && response.workflow && response.routing,
    );
    if (!hasExecutionContract) {
      const providerDisabled = getRuntimeFailureKind(response.report) === 'provider-disabled';
      return [
        {
          id: 'runtime',
          name: labels.runtime,
          description: labels.runtimeFailed,
          status: 'failed',
        },
        {
          id: 'provider',
          name: labels.provider,
          description: providerDisabled ? labels.providerDisabled : labels.providerFailed,
          status: 'failed',
        },
      ];
    }

    const strategy = response.execution?.strategy ?? '';
    const provider = response.routing?.provider ?? '';
    const workflowType = response.workflow?.type ?? '';
    const intent = response.reasoning?.intent || labels.unclassified;
    const companies = response.reasoning?.companies || [];
    const citationCount = response.citations?.length || 0;
    const executionTime = response.execution_time
      ? `${response.execution_time.toFixed(2)}s`
      : labels.notAvailable;
    const planSteps = response.plan?.steps?.length ?? 0;
    const planDescription = response.plan?.steps?.length
      ? labels.executedSteps(planSteps)
      : labels.builtPlan;

    return [
      {
        id: 'intent',
        name: labels.intentAnalyzer,
        description: labels.detectedIntent(intent, companies),
        status: 'completed',
      },
      {
        id: 'planner',
        name: labels.queryPlanner,
        description: labels.planForWorkflow(planDescription, workflowType),
        status: 'completed',
      },
      {
        id: 'retriever',
        name: labels.hybridRetriever,
        description: labels.retrievedEvidence(citationCount),
        status: 'completed',
      },
      {
        id: 'ranker',
        name: labels.evidenceRanking,
        description: labels.rankedResults,
        status: 'completed',
      },
      {
        id: 'generator',
        name: labels.llmGeneration,
        description: labels.generatedReport(provider, strategy, executionTime),
        status: 'completed',
      },
    ];
  }

  if (loading) {
    return [
      {
        id: 'intent',
        name: labels.intentAnalyzer,
        description: labels.classifyingIntent,
        status: 'completed',
      },
      {
        id: 'planner',
        name: labels.queryPlanner,
        description: labels.buildingPlan,
        status: 'completed',
      },
      {
        id: 'retriever',
        name: labels.hybridRetriever,
        description: labels.searchingKnowledge,
        status: 'running',
      },
      {
        id: 'ranker',
        name: labels.evidenceRanking,
        description: labels.waitingForRetrieval,
        status: 'pending',
      },
      {
        id: 'generator',
        name: labels.llmGeneration,
        description: labels.waitingForEvidence,
        status: 'pending',
      },
    ];
  }

  return [
    {
      id: 'intent',
      name: labels.intentAnalyzer,
      description: labels.classifiesIntent,
      status: 'pending',
    },
    {
      id: 'planner',
      name: labels.queryPlanner,
      description: labels.buildsPlan,
      status: 'pending',
    },
    {
      id: 'retriever',
      name: labels.hybridRetriever,
      description: labels.searchesEvidence,
      status: 'pending',
    },
    {
      id: 'ranker',
      name: labels.evidenceRanking,
      description: labels.ranksEvidence,
      status: 'pending',
    },
    {
      id: 'generator',
      name: labels.llmGeneration,
      description: labels.generatesReport,
      status: 'pending',
    },
  ];
}

export function AgentTimeline({
  response,
  loading,
  title,
  emptyMessage,
}: AgentTimelineProps) {
  const { t } = useLanguage();
  const steps = buildTimeline(response, loading, t.agent);
  const hasResponse = response !== null;
  const [open, setOpen] = useState(false);
  const status = loading
    ? 'running'
    : isSafeStructuredRefusal(response)
      ? 'safe_refusal'
    : steps.some((step) => step.status === 'failed')
      ? 'failed'
      : hasResponse
        ? 'completed'
        : 'pending';

  useEffect(() => {
    setOpen(false);
  }, [loading, response]);

  return (
    <details
      className="agent-timeline-panel"
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary aria-label={`${title ?? t.agent.title}: ${t.agent.status[status]}`}>
        <span
          id="agent-timeline-title"
          className="agent-timeline-panel__title"
        >
          {title ?? t.agent.title}
        </span>{' '}
        <span className="agent-timeline-panel__summary-value">
          {t.agent.status[status]}
        </span>
      </summary>

      <div className="agent-timeline-panel__body">
        {!hasResponse && !loading && (
          <p className="agent-timeline-panel__empty">
            {emptyMessage ?? t.agent.empty}
          </p>
        )}

        <div className="agent-timeline">
          {steps.map((step, index) => (
            <AgentStep
              key={step.id}
              step={step}
              isLast={index === steps.length - 1}
            />
          ))}
        </div>

        {hasResponse && response?.workflow && (
          <div className="agent-timeline-panel__summary">
            <span className="agent-timeline-panel__summary-label">
              {t.agent.workflow}
            </span>
            <span className="agent-timeline-panel__summary-value">
              {response.workflow.type}
            </span>
          </div>
        )}
      </div>
    </details>
  );
}
