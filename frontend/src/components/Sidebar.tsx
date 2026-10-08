import type { Language } from '../types/language';
import { useLanguage } from '../i18n/LanguageContext';

interface SidebarProps {
  language: Language;
  onLanguageChange: (language: Language) => void;
  labels: {
    runtime: string;
    title: string;
    demoCompanies: string;
    language: string;
  };
}

export function Sidebar({ language, onLanguageChange, labels }: SidebarProps) {
  const i18n = useLanguage();

  return (
    <aside className="sidebar">
      <div>
        <p className="eyebrow">{labels.runtime}</p>
        <h1>{labels.title}</h1>
      </div>

      <div className="language-switcher" aria-label={labels.language}>
        <button
          type="button"
          className={language === 'en' ? 'language-switcher__button--active' : ''}
          aria-pressed={language === 'en'}
          onClick={() => onLanguageChange('en')}
        >
          EN
        </button>
        <button
          type="button"
          className={language === 'zh-CN' ? 'language-switcher__button--active' : ''}
          aria-pressed={language === 'zh-CN'}
          onClick={() => onLanguageChange('zh-CN')}
        >
          中文
        </button>
      </div>

      <nav aria-label={labels.demoCompanies}>
        <p className="sidebar__label">{labels.demoCompanies}</p>
        <ul>
          {i18n.t.sidebar.companies.map((company) => (
            <li key={company}>{company}</li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}
