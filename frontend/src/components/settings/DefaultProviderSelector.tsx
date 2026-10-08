import { useEffect, useRef, useState } from 'react';
import { useLanguage } from '../../i18n/LanguageContext';
import type { LLMProvider, ProviderSettings } from '../../types/settings';

interface DefaultProviderSelectorProps {
  providers: ProviderSettings[];
  onSelect: (provider: LLMProvider) => Promise<void>;
}

export function DefaultProviderSelector({
  providers,
  onSelect,
}: DefaultProviderSelectorProps) {
  const { t } = useLanguage();
  const currentDefault = providers.find((provider) => provider.is_default);
  const initialProvider = currentDefault ?? providers[0];
  const [selectedProvider, setSelectedProvider] = useState(initialProvider?.provider ?? '');
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<'saved' | 'error' | null>(null);
  const selectedRef = useRef(selectedProvider);
  const busyRef = useRef(false);

  useEffect(() => {
    const next = providers.find((provider) => provider.is_default) ?? providers[0];
    const provider = next?.provider ?? '';
    setSelectedProvider(provider);
    selectedRef.current = provider;
  }, [providers]);

  const select = async (provider: ProviderSettings | undefined) => {
    if (!provider || busyRef.current) return;
    if (provider.provider === currentDefault?.provider) {
      selectedRef.current = provider.provider;
      setSelectedProvider(provider.provider);
      return;
    }

    busyRef.current = true;
    setBusy(true);
    setFeedback(null);
    try {
      await onSelect(provider.provider);
      setFeedback('saved');
    } catch {
      const fallback = currentDefault ?? providers[0];
      selectedRef.current = fallback?.provider ?? '';
      setSelectedProvider(selectedRef.current);
      setFeedback('error');
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  const selectedIndex = Math.max(
    0,
    providers.findIndex((provider) => provider.provider === selectedProvider),
  );
  const selected = providers[selectedIndex];
  const valueText = selected
    ? t.settings.defaultSelectionValue(selected.display_name, selectedIndex + 1, providers.length)
    : '';

  return (
    <section className="default-provider" aria-labelledby="default-provider-title">
      <div className="default-provider__copy">
        <div>
          <h3 id="default-provider-title">{t.settings.defaultSelectionTitle}</h3>
          <p id="default-provider-description">{t.settings.defaultSelectionDescription}</p>
        </div>
        {selected && (
          <output className="default-provider__current" aria-live="polite">
            {selected.display_name}
          </output>
        )}
      </div>

      {providers.length === 1 ? (
        providers[0].is_default ? (
          <output className="default-provider__current">
            {t.settings.defaultProvider}
          </output>
        ) : (
          <button
            type="button"
            className="settings-button settings-button--primary default-provider__single-action"
            disabled={busy}
            onClick={() => void select(providers[0])}
          >
            {busy ? t.settings.defaultSelectionSaving : t.settings.defaultSelectionUseSingle}
          </button>
        )
      ) : (
        <>
          <div className={`default-provider__slider${busy ? ' is-busy' : ''}`}>
            <input
              aria-label={t.settings.defaultSelectionLabel}
              aria-describedby="default-provider-description"
              aria-valuetext={valueText}
              type="range"
              min={0}
              max={providers.length - 1}
              step={1}
              value={selectedIndex}
              disabled={busy}
              onChange={(event) => {
                const next = providers[Number(event.currentTarget.value)];
                selectedRef.current = next?.provider ?? '';
                setSelectedProvider(selectedRef.current);
                setFeedback(null);
              }}
              onPointerUp={() => {
                const next = providers.find((provider) => provider.provider === selectedRef.current);
                void select(next);
              }}
              onKeyUp={(event) => {
                if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) {
                  const next = providers.find((provider) => provider.provider === selectedRef.current);
                  void select(next);
                }
              }}
              onBlur={() => {
                const next = providers.find((provider) => provider.provider === selectedRef.current);
                void select(next);
              }}
            />
          </div>
          <div
            className="default-provider__options"
            role="group"
            aria-label={t.settings.defaultSelectionLabel}
          >
            {providers.map((provider, index) => (
              <button
                key={provider.provider}
                type="button"
                className={provider.provider === selectedProvider ? 'is-selected' : ''}
                disabled={busy}
                aria-pressed={provider.provider === selectedProvider}
                onClick={() => {
                  selectedRef.current = provider.provider;
                  setSelectedProvider(provider.provider);
                  setFeedback(null);
                  void select(provider);
                }}
              >
                <span>{provider.display_name}</span>
                {provider.is_default && <small>{t.settings.defaultProvider}</small>}
              </button>
            ))}
          </div>
        </>
      )}

      <p
        className={`default-provider__feedback${feedback === 'error' ? ' is-error' : ''}`}
        role={feedback === 'error' ? 'alert' : 'status'}
        aria-live="polite"
      >
        {busy
          ? t.settings.defaultSelectionSaving
          : feedback === 'saved'
            ? t.settings.defaultSelectionSaved
            : feedback === 'error'
              ? t.settings.defaultSelectionFailed
              : ''}
      </p>
    </section>
  );
}
