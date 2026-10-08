import type { StepStatus } from './StatusBadge';
import { StatusBadge } from './StatusBadge';

export interface AgentStepData {
  id: string;
  name: string;
  description: string;
  status: StepStatus;
  duration?: string;
}

interface AgentStepProps {
  step: AgentStepData;
  isLast: boolean;
}

export function AgentStep({ step, isLast }: AgentStepProps) {
  return (
    <div className="agent-step">
      <div className="agent-step__connector">
        <div className={`agent-step__dot agent-step__dot--${step.status}`} />
        {!isLast && <div className="agent-step__line" />}
      </div>
      <div className="agent-step__content">
        <div className="agent-step__header">
          <span className="agent-step__name">{step.name}</span>
          <StatusBadge status={step.status} />
        </div>
        <p className="agent-step__description">{step.description}</p>
        {step.duration && (
          <span className="agent-step__duration">{step.duration}</span>
        )}
      </div>
    </div>
  );
}