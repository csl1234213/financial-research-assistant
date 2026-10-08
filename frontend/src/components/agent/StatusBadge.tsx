import { useLanguage } from '../../i18n/LanguageContext';

export type StepStatus = 'completed' | 'running' | 'pending' | 'failed' | 'safe_refusal';

interface StatusBadgeProps {
  status: StepStatus;
}

const statusIcons: Record<StepStatus, string> = {
  safe_refusal: '\u2014',
  completed: '\u2713',
  running: '\u25CF',
  pending: '\u25CB',
  failed: '\u2717',
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const { t } = useLanguage();
  const label = t.agent.status[status];

  return (
    <span className={`status-badge status-badge--${status}`} aria-label={label}>
      <span className="status-badge__icon" aria-hidden="true">
        {statusIcons[status]}
      </span>
      {label}
    </span>
  );
}
