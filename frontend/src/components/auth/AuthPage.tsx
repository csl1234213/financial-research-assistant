import { useState, type FormEvent } from 'react';
import { loginUser, registerUser } from '../../api/auth';
import { useLanguage } from '../../i18n/LanguageContext';
import type { AuthUser } from '../../types/auth';
import { LanguageSwitcher } from '../LanguageSwitcher';
import { Icon } from '../ui/Icon';

type AuthMode = 'login' | 'register';

interface AuthPageProps {
  onAuthenticated: (user: AuthUser) => void;
}

export function AuthPage({ onAuthenticated }: AuthPageProps) {
  const { t } = useLanguage();
  const [mode, setMode] = useState<AuthMode>('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const switchMode = (nextMode: AuthMode) => {
    setMode(nextMode);
    setError(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;

    setSubmitting(true);
    setError(null);

    try {
      const user = mode === 'register'
        ? await registerUser(email.trim(), password)
        : await loginUser(email.trim(), password);
      onAuthenticated(user);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t.auth.failed);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-card__language">
          <LanguageSwitcher compact />
        </div>
        <div className="auth-card__brand" aria-hidden="true">
          <Icon name="financial-research" />
        </div>
        <p className="auth-card__eyebrow">{t.auth.eyebrow}</p>
        <h1 id="auth-title">
          {mode === 'register' ? t.auth.registerTitle : t.auth.loginTitle}
        </h1>
        <p className="auth-card__subtitle">
          {mode === 'register'
            ? t.auth.registerSubtitle
            : t.auth.loginSubtitle}
        </p>

        <div className="auth-tabs" role="tablist" aria-label={t.auth.modeLabel}>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'login'}
            className={mode === 'login' ? 'auth-tabs__button auth-tabs__button--active' : 'auth-tabs__button'}
            onClick={() => switchMode('login')}
          >
            {t.auth.login}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === 'register'}
            className={mode === 'register' ? 'auth-tabs__button auth-tabs__button--active' : 'auth-tabs__button'}
            onClick={() => switchMode('register')}
          >
            {t.auth.register}
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === 'register' && (
            <label className="auth-field">
              <span>{t.auth.name}</span>
              <input
                type="text"
                name="name"
                autoComplete="name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                required
                disabled={submitting}
              />
            </label>
          )}

          <label className="auth-field">
            <span>{t.auth.email}</span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              disabled={submitting}
            />
          </label>

          <label className="auth-field">
            <span>{t.auth.password}</span>
            <input
              type="password"
              name="password"
              autoComplete={mode === 'register' ? 'new-password' : 'current-password'}
              minLength={6}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              disabled={submitting}
            />
          </label>

          {error && (
            <p className="auth-form__error" role="alert">
              {error}
            </p>
          )}

          <button className="auth-form__submit" type="submit" disabled={submitting}>
            {submitting
              ? (mode === 'register' ? t.auth.creatingAccount : t.auth.signingIn)
              : (mode === 'register' ? t.auth.createAccount : t.auth.signIn)}
          </button>
        </form>
      </section>
    </main>
  );
}
