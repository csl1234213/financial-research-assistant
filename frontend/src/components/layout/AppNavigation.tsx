import { useLanguage } from '../../i18n/LanguageContext';
import { Icon, type IconName } from '../ui/Icon';

export type NavigationPage = 'chat' | 'knowledge' | 'retrieval' | 'settings';

interface AppNavigationProps {
  currentPage: NavigationPage;
  email: string;
  onNavigate: (page: NavigationPage) => void;
  onNewChat: () => void;
  onLogout: () => void;
}

interface NavigationItem {
  page: NavigationPage;
  icon: IconName;
  label: string;
}

export function AppNavigation({
  currentPage,
  email,
  onNavigate,
  onNewChat,
  onLogout,
}: AppNavigationProps) {
  const { t } = useLanguage();
  const items: NavigationItem[] = [
    { page: 'chat', icon: 'chat', label: t.app.nav.chat },
    { page: 'knowledge', icon: 'folder', label: t.app.nav.knowledge },
    { page: 'retrieval', icon: 'search', label: t.app.nav.retrieval },
    { page: 'settings', icon: 'sliders', label: t.app.nav.settings },
  ];

  return (
    <nav className="app-nav" aria-label={t.header.title}>
      <div className="app-nav__identity">
        <span className="app-nav__mark" aria-hidden="true">
          <Icon name="financial-research" />
        </span>
        <span className="app-nav__wordmark">{t.header.title}</span>
      </div>

      <button
        type="button"
        className="app-nav__new-chat"
        onClick={onNewChat}
        aria-label={t.app.nav.newChat}
        title={t.app.nav.newChat}
      >
        <Icon name="plus" />
        <span>{t.app.nav.newChat}</span>
      </button>

      <div className="app-nav__pages">
        {items.map((item) => {
          const active = currentPage === item.page;
          return (
            <button
              key={item.page}
              type="button"
              className={`app-nav__link ${active ? 'app-nav__link--active' : ''}`}
              aria-current={active ? 'page' : undefined}
              onClick={() => onNavigate(item.page)}
            >
              <Icon name={item.icon} className="app-nav__icon" />
              <span className="app-nav__label">{item.label}</span>
            </button>
          );
        })}
      </div>

      <div className="app-nav__account">
        <div className="app-nav__user">
          <span className="app-nav__avatar" aria-hidden="true">
            {email.slice(0, 1).toUpperCase()}
          </span>
          <span className="app-nav__email" title={email}>{email}</span>
        </div>
        <button
          type="button"
          className="app-nav__logout"
          onClick={onLogout}
          aria-label={t.app.nav.logout}
          title={t.app.nav.logout}
        >
          <Icon name="logout" />
          <span>{t.app.nav.logout}</span>
        </button>
      </div>
    </nav>
  );
}
