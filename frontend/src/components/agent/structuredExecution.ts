import type { ChatResponse } from '../../types/api';

export function isSafeStructuredRefusal(response: ChatResponse | null): boolean {
  return response !== null
    && response.execution?.strategy === 'structured_financial_fact'
    && ['UNSUPPORTED_METRIC', 'NOT_FOUND', 'AMBIGUOUS', 'CONFLICT'].includes(String(response.execution.status))
    && response.execution.provider_calls === 0
    && response.workflow?.type === 'structured_financial_fact'
    && response.workflow.status === 'safe_failure'
    && response.citations.length === 0;
}

/** Missing routing is expected only for an explicitly successful zero-provider fact lookup. */
export function isCompletedStructuredFact(response: ChatResponse | null): boolean {
  return response !== null
    && response.execution?.strategy === 'structured_financial_fact'
    && response.execution.status === 'FOUND'
    && response.execution.provider_calls === 0
    && response.workflow?.type === 'structured_financial_fact'
    && response.workflow.status === 'completed'
    && response.citations.length > 0;
}
