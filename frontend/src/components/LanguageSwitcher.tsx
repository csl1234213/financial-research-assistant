import { useLanguage } from '../i18n/LanguageContext';

interface LanguageSwitcherProps {
  compact?: boolean;
}

export function LanguageSwitcher({ compact = false }: LanguageSwitcherProps) {
  const { language, setLanguage, t } = useLanguage();

  return (
    <div
      className={`language-switcher ${compact ? 'language-switcher--compact' : ''}`}
      aria-label={t.language.label}
    >
      <button
        type="button"
        className={language === 'en' ? 'language-switcher__button--active' : ''}
        aria-pressed={language === 'en'}
        title={t.language.english}
        onClick={() => setLanguage('en')}
      >
        EN
      </button>
      <button
        type="button"
        className={language === 'zh-CN' ? 'language-switcher__button--active' : ''}
        aria-pressed={language === 'zh-CN'}
        title={t.language.chinese}
        onClick={() => setLanguage('zh-CN')}
      >
        中文
      </button>
    </div>
  );
}
