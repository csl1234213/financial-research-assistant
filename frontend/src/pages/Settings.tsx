import { useCallback, useEffect, useState } from 'react';
import {
  clearLLMProvider,
  getLLMSettings,
  setDefaultLLMProvider,
  updateLLMProvider,
} from '../api/settings';
import { ErrorBoundary } from '../components/ErrorBoundary';
import { LanguageSwitcher } from '../components/LanguageSwitcher';
import { Header } from '../components/layout/Header';
import { DefaultProviderSelector } from '../components/settings/DefaultProviderSelector';
import { ProviderKeyCard } from '../components/settings/ProviderKeyCard';
import { ThemeSelector } from '../components/settings/ThemeSelector';
import { Icon } from '../components/ui/Icon';
import { useLanguage } from '../i18n/LanguageContext';
import type { LLMProvider, ProviderSettings } from '../types/settings';

export function Settings() {
  const { t } = useLanguage();
  const [providers, setProviders] = useState<ProviderSettings[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  const loadProviders = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const response = await getLLMSettings();
      setProviders(response.providers);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  const replaceProvider = useCallback((updated: ProviderSettings) => {
    setProviders((current) => (
      current.map((provider) => (
        provider.provider === updated.provider ? updated : provider
      ))
    ));
  }, []);

  const handleSave = useCallback(async (
    provider: LLMProvider,
    apiKey: string,
    model: string,
    baseUrl?: string,
  ) => {
    const updated = await updateLLMProvider(provider, apiKey, model, baseUrl);
    replaceProvider(updated);
  }, [replaceProvider]);

  const handleClear = useCallback(async (provider: LLMProvider) => {
    await clearLLMProvider(provider);
    await loadProviders();
  }, [loadProviders]);

  const handleSetDefault = useCallback(async (provider: LLMProvider) => {
    const response = await setDefaultLLMProvider(provider);
    setProviders(response.providers);
  }, []);

  return (
    <ErrorBoundary labels={t.errorBoundary}>
      <div className="app-layout">
        <Header
          title={t.header.title}
          subtitle={t.header.settingsSubtitle}
          connected={!loadError}
        />

        <main className="settings-page">
          <div className="settings-page__intro">
            <p className="eyebrow">{t.header.settingsSubtitle}</p>
            <h1>{t.settings.title}</h1>
            <p>{t.settings.subtitle}</p>
          </div>

          <section className="settings-section" aria-labelledby="appearance-title">
            <div className="settings-section__header">
              <div>
                <h2 id="appearance-title">{t.settings.appearanceTitle}</h2>
                <p>{t.settings.appearanceDescription}</p>
              </div>
            </div>

            <div className="settings-section__content settings-appearance">
              <div className="settings-preference">
                <div>
                  <h3>{t.settings.themeLabel}</h3>
                </div>
                <ThemeSelector />
              </div>
              <div className="settings-preference settings-preference--language">
                <div>
                  <h3>{t.settings.languageTitle}</h3>
                  <p>{t.settings.languageDescription}</p>
                </div>
                <LanguageSwitcher />
              </div>
            </div>
          </section>

          <section className="settings-section" aria-labelledby="llm-settings-title">
            <div className="settings-section__header">
              <div>
                <h2 id="llm-settings-title">{t.settings.llmTitle}</h2>
                <p>{t.settings.llmDescription}</p>
              </div>
            </div>

            <div className="settings-security-note">
              <Icon name="lock" />
              <p>{t.settings.securityNote}</p>
            </div>

            {loading && (
              <div className="settings-state" role="status">
                <span className="settings-state__spinner" aria-hidden="true" />
                {t.settings.loading}
              </div>
            )}

            {!loading && loadError && (
              <div className="settings-state settings-state--error" role="alert">
                <span>{t.settings.loadError}</span>
                <button
                  type="button"
                  className="settings-button settings-button--secondary"
                  onClick={loadProviders}
                >
                  {t.settings.retry}
                </button>
              </div>
            )}

            {!loading && !loadError && providers.length === 0 && (
              <div className="settings-state">{t.settings.noProviders}</div>
            )}

            {!loading && !loadError && providers.length > 0 && (
              <>
                {providers.some((provider) => provider.configured) && (
                  <DefaultProviderSelector
                    providers={providers.filter((provider) => provider.configured)}
                    onSelect={handleSetDefault}
                  />
                )}
                <div className="provider-grid">
                  {providers.map((provider) => (
                    <ProviderKeyCard
                      key={provider.provider}
                      settings={provider}
                      onSave={handleSave}
                      onClear={handleClear}
                    />
                  ))}
                </div>
              </>
            )}
          </section>
        </main>
      </div>
    </ErrorBoundary>
  );
}
