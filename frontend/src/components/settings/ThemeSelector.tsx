import { useLanguage } from '../../i18n/LanguageContext';
import { useTheme, type Theme } from '../../theme/ThemeContext';
import { Icon, type IconName } from '../ui/Icon';

interface ThemeOption {
  value: Theme;
  icon: IconName;
  label: string;
  description: string;
}

export function ThemeSelector() {
  const { t } = useLanguage();
  const { theme, setTheme } = useTheme();

  const options: ThemeOption[] = [
    {
      value: 'light',
      icon: 'sun',
      label: t.settings.lightTheme,
      description: t.settings.lightThemeDescription,
    },
    {
      value: 'dark',
      icon: 'moon',
      label: t.settings.darkTheme,
      description: t.settings.darkThemeDescription,
    },
  ];

  return (
    <div className="theme-selector" role="group" aria-label={t.settings.themeLabel}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className={`theme-selector__option theme-selector__option--${option.value} ${
            theme === option.value ? 'theme-selector__option--active' : ''
          }`}
          aria-pressed={theme === option.value}
          onClick={() => setTheme(option.value)}
        >
          <span className="theme-selector__preview" aria-hidden="true">
            <span className="theme-selector__preview-header" />
            <span className="theme-selector__preview-body">
              <span />
              <span />
              <span />
            </span>
          </span>
          <span className="theme-selector__copy">
            <span className="theme-selector__title">
              <Icon name={option.icon} />
              {option.label}
            </span>
            <span className="theme-selector__description">{option.description}</span>
          </span>
          <span className="theme-selector__check" aria-hidden="true">
            {theme === option.value ? '✓' : ''}
          </span>
        </button>
      ))}
    </div>
  );
}
