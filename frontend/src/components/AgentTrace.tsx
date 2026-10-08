import type { ChatResponse } from '../types/chat';

interface AgentTraceProps {
  response: ChatResponse | null;
  labels: {
    title: string;
    empty: string;
    reasoning: string;
    intent: string;
    companies: string;
    researchMode: string;
    execution: string;
    strategy: string;
    provider: string;
    workflow: string;
    type: string;
    status: string;
  };
}

export function AgentTrace({ response, labels }: AgentTraceProps) {
  if (!response) {
    return (
      <section className="panel" aria-labelledby="agent-trace-title">
        <h2 id="agent-trace-title">{labels.title}</h2>
        <p className="panel__empty">{labels.empty}</p>
      </section>
    );
  }

  const traceGroups = [
    {
      title: labels.reasoning,
      items: [
        [labels.intent, response.reasoning.intent],
        [labels.companies, response.reasoning.companies.join(', ')],
        [labels.researchMode, response.reasoning.research_mode],
      ],
    },
    {
      title: labels.execution,
      items: [
        [labels.strategy, response.execution?.strategy ?? 'N/A'],
        [labels.provider, response.routing?.provider ?? 'N/A'],
      ],
    },
    {
      title: labels.workflow,
      items: [
        [labels.type, response.workflow?.type ?? 'N/A'],
        [labels.status, response.workflow?.status ?? 'N/A'],
      ],
    },
  ];

  return (
    <section className="panel" aria-labelledby="agent-trace-title">
      <h2 id="agent-trace-title">{labels.title}</h2>
      <div className="trace-groups">
        {traceGroups.map((group) => (
          <section className="trace-group" key={group.title}>
            <h3>{group.title}</h3>
            <dl className="trace-list">
              {group.items.map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </section>
  );
}
