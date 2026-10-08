import { useEffect, useState, type FormEvent } from 'react';
import { useLanguage } from '../../i18n/LanguageContext';
import type { LLMProvider, ProviderSettings } from '../../types/settings';

type Feedback =
  | 'saved'
  | 'cleared'
  | 'save-error'
  | 'clear-error'
  | null;
type Operation = 'saving' | 'clearing' | null;

interface ProviderKeyCardProps {
  settings: ProviderSettings;
  onSave: (
    provider: LLMProvider,
    apiKey: string,
    model: string,
    baseUrl?: string,
  ) => Promise<void>;
  onClear: (provider: LLMProvider) => Promise<void>;
}

function formatKeyHint(keyHint: string | null): string | null {
  if (!keyHint) return null;
  return `•••• ${keyHint.slice(-4)}`;
}

function formatUpdatedAt(
  value: string | null,
  language: string,
  fallback: string,
): string {
  if (!value) return fallback;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return fallback;
  return new Intl.DateTimeFormat(language, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export function ProviderKeyCard({
  settings,
  onSave,
  onClear,
}: ProviderKeyCardProps) {
  const { language, t } = useLanguage();
  const [apiKey, setApiKey] = useState('');
  const [model, setModel] = useState(settings.model);
  const [baseUrl, setBaseUrl] = useState(settings.base_url ?? '');
  const [operation, setOperation] = useState<Operation>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [confirmingClear, setConfirmingClear] = useState(false);

  useEffect(() => {
    setModel(settings.model);
  }, [settings.model]);

  useEffect(() => {
    setBaseUrl(settings.base_url ?? '');
  }, [settings.base_url]);

  const isLocalModel = settings.provider === 'ollama';

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const localChanged = isLocalModel
      && (!settings.configured
        || model !== settings.model
        || baseUrl !== (settings.base_url ?? ''));
    const modelChanged = settings.configured && model !== settings.model;
    if ((!apiKey.trim() && !modelChanged && !localChanged) || operation) return;

    setOperation('saving');
    setFeedback(null);
    try {
      await onSave(settings.provider, apiKey, model, baseUrl);
      setApiKey('');
      setFeedback('saved');
    } catch {
      setFeedback('save-error');
    } finally {
      setOperation(null);
    }
  };

  const handleClear = async () => {
    if (operation) return;

    setOperation('clearing');
    setFeedback(null);
    try {
      await onClear(settings.provider);
      setApiKey('');
      setConfirmingClear(false);
      setFeedback('cleared');
    } catch {
      setFeedback('clear-error');
    } finally {
      setOperation(null);
    }
  };

  const updatedAt = formatUpdatedAt(
    settings.updated_at,
    language,
    t.settings.neverUpdated,
  );
  const keyHint = formatKeyHint(settings.key_hint);
  const modelOptions = settings.model && !settings.models.includes(settings.model)
    ? [settings.model, ...settings.models]
    : settings.models;
  const feedbackMessage = feedback === 'saved'
    ? t.settings.saved
    : feedback === 'cleared'
      ? t.settings.cleared
      : feedback === 'save-error'
        ? t.settings.saveError
        : feedback === 'clear-error'
          ? t.settings.clearError
          : null;
  const canSave = Boolean(
    isLocalModel
      ? model.trim()
        && baseUrl.trim()
        && (!settings.configured
          || model !== settings.model
          || baseUrl !== (settings.base_url ?? ''))
      : apiKey.trim() || (settings.configured && model !== settings.model),
  );

  return (
    <article className="provider-card" aria-labelledby={`provider-${settings.provider}`}>
      <div className="provider-card__header">
        <div>
          <h3 id={`provider-${settings.provider}`}>{settings.display_name}</h3>
          <span className="provider-card__id">{settings.provider}</span>
        </div>
        <span
          className={`provider-card__status ${
            settings.configured
              ? 'provider-card__status--configured'
              : 'provider-card__status--empty'
          }`}
        >
          <span aria-hidden="true">{settings.configured ? '●' : '○'}</span>
          {settings.configured
            ? t.settings.configured
            : t.settings.notConfigured}
        </span>
        {settings.is_default && (
          <span className="provider-card__default-badge">
            {t.settings.defaultProvider}
          </span>
        )}
      </div>

      <dl className="provider-card__metadata">
        <div>
          <dt>{isLocalModel ? t.settings.localEndpointLabel : t.settings.keyHint}</dt>
          <dd>{isLocalModel ? (settings.base_url ?? '—') : (keyHint ?? '—')}</dd>
        </div>
        <div>
          <dt>{t.settings.updatedAt}</dt>
          <dd>{updatedAt}</dd>
        </div>
      </dl>

      <form className="provider-card__form" onSubmit={handleSave}>
        {isLocalModel ? (
          <label className="settings-field">
            <span>{t.settings.localEndpointLabel}</span>
            <input
              type="url"
              name="ollama-base-url"
              autoComplete="url"
              spellCheck={false}
              value={baseUrl}
              placeholder={t.settings.localEndpointPlaceholder}
              disabled={operation !== null}
              onChange={(event) => {
                setBaseUrl(event.target.value);
                setFeedback(null);
              }}
            />
            <small>{t.settings.localEndpointHelp}</small>
          </label>
        ) : (
          <label className="settings-field">
            <span>{t.settings.apiKeyLabel}</span>
            <input
              type="password"
              minLength={8}
              name={`${settings.provider}-api-key`}
              autoComplete="new-password"
              spellCheck={false}
              value={apiKey}
              placeholder={t.settings.apiKeyPlaceholder}
              disabled={operation !== null}
              onChange={(event) => {
                setApiKey(event.target.value);
                setFeedback(null);
              }}
            />
          </label>
        )}

        <label className="settings-field">
          <span>{isLocalModel ? t.settings.localModelLabel : t.settings.modelLabel}</span>
          {isLocalModel ? (
            <input
              type="text"
              name="ollama-model"
              autoComplete="off"
              spellCheck={false}
              value={model}
              placeholder={t.settings.localModelPlaceholder}
              disabled={operation !== null}
              onChange={(event) => {
                setModel(event.target.value);
                setFeedback(null);
              }}
            />
          ) : (
            <select
              name={`${settings.provider}-model`}
              value={model}
              disabled={operation !== null}
              onChange={(event) => {
                setModel(event.target.value);
                setFeedback(null);
              }}
            >
              <option value="">{t.settings.modelPlaceholder}</option>
              {modelOptions.map((modelName) => (
                <option key={modelName} value={modelName}>
                  {modelName}
                </option>
              ))}
            </select>
          )}
          {isLocalModel && <small>{t.settings.localModelHelp}</small>}
        </label>

        {feedbackMessage && (
          <p
            className={`provider-card__feedback ${
              feedback === 'save-error'
                || feedback === 'clear-error'
                ? 'provider-card__feedback--error'
                : 'provider-card__feedback--success'
            }`}
            role={
              feedback === 'save-error'
                || feedback === 'clear-error'
                ? 'alert'
                : 'status'
            }
          >
            {feedbackMessage}
          </p>
        )}

        {confirmingClear && (
          <div className="provider-card__confirmation" role="alert">
              <strong>{isLocalModel ? t.settings.confirmClearLocal : t.settings.confirmClear}</strong>
            <span>{t.settings.confirmClearDescription}</span>
            <div>
              <button
                type="button"
                className="settings-button settings-button--danger"
                disabled={operation !== null}
                onClick={handleClear}
              >
                {operation === 'clearing' ? t.settings.clearing : t.settings.clear}
              </button>
              <button
                type="button"
                className="settings-button settings-button--secondary"
                disabled={operation !== null}
                onClick={() => setConfirmingClear(false)}
              >
                {t.settings.cancel}
              </button>
            </div>
          </div>
        )}

        <div className="provider-card__actions">
          <button
            type="submit"
            className="settings-button settings-button--primary"
            disabled={!canSave || operation !== null}
          >
            {operation === 'saving' ? t.settings.saving : t.settings.save}
          </button>
          {settings.configured && !confirmingClear && (
            <button
              type="button"
              className="settings-button settings-button--secondary"
              disabled={operation !== null}
              onClick={() => {
                setConfirmingClear(true);
                setFeedback(null);
              }}
            >
              {t.settings.clear}
            </button>
          )}
        </div>
      </form>
    </article>
  );
}
