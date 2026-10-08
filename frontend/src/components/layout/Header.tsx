import { useLanguage } from '../../i18n/LanguageContext';
import { LanguageSwitcher } from '../LanguageSwitcher';

interface HeaderProps {
  title: string;
  subtitle: string;
  connected?: boolean;
}

export function Header({ title, subtitle, connected = true }: HeaderProps) {
  const { t } = useLanguage();

  return (
    <header className="app-header">
      <div className="app-header__context">
        <span className="app-header__title">{subtitle}</span>
        <span className="app-header__subtitle">{title}</span>
      </div>

      <div className="app-header__tools">
        <LanguageSwitcher compact />
        <div className={`app-header__status ${connected ? '' : 'app-header__status--offline'}`} aria-label={t.header.systemStatus}>
          <span className="app-header__status-dot" aria-hidden="true" />
          {connected ? t.header.connected : t.header.offline}
        </div>
      </div>
    </header>
  );
}
