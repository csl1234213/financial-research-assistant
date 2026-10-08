import type { SVGProps } from 'react';

export type IconName =
  | 'arrow-up'
  | 'chat'
  | 'chevron-left'
  | 'chevron-right'
  | 'clipboard'
  | 'clock'
  | 'document'
  | 'folder'
  | 'financial-research'
  | 'ledger'
  | 'lock'
  | 'logout'
  | 'moon'
  | 'paperclip'
  | 'plus'
  | 'search'
  | 'sliders'
  | 'sun';

interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'name'> {
  name: IconName;
}

function IconPaths({ name }: { name: IconName }) {
  switch (name) {
    case 'arrow-up':
      return (
        <>
          <path d="M12 19V5" />
          <path d="m6.5 10.5 5.5-5.5 5.5 5.5" />
        </>
      );
    case 'chat':
      return (
        <>
          <path d="M20 15.5a4 4 0 0 1-4 4H8l-5 2.5V7.5a4 4 0 0 1 4-4h9a4 4 0 0 1 4 4Z" />
          <path d="M8 9h8M8 13h5" />
        </>
      );
    case 'chevron-left':
      return <path d="m15 18-6-6 6-6" />;
    case 'chevron-right':
      return <path d="m9 18 6-6-6-6" />;
    case 'clipboard':
      return (
        <>
          <rect x="5" y="4" width="14" height="17" rx="2" />
          <path d="M9 4.5V3h6v1.5M8.5 9h7M8.5 13h7M8.5 17h4" />
        </>
      );
    case 'clock':
      return (
        <>
          <circle cx="12" cy="13" r="8" />
          <path d="M12 9v4l2.5 1.5M9 2h6M12 5V2" />
        </>
      );
    case 'document':
      return (
        <>
          <path d="M6 2.5h8l4 4V21H6Z" />
          <path d="M14 2.5V7h4M9 12h6M9 16h6" />
        </>
      );
    case 'folder':
      return (
        <>
          <path d="M3 6.5h7l2 2h9v9a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3Z" />
          <path d="M3 10h18" />
        </>
      );
    case 'financial-research':
      return (
        <>
          <path d="M6 3h8l4 4v14H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
          <path d="M14 3v4h4M8 9h3M8 17l3-3 2 1 3-4" />
        </>
      );
    case 'ledger':
      return (
        <>
          <path d="M5 3.5h14v17H5Z" />
          <path d="M9 3.5v17M12 8h4M12 12h4M12 16h4" />
        </>
      );
    case 'lock':
      return (
        <>
          <rect x="4.5" y="10" width="15" height="11" rx="2" />
          <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14.5v2" />
        </>
      );
    case 'logout':
      return (
        <>
          <path d="M10 4H5v16h5M14 8l4 4-4 4M8 12h10" />
        </>
      );
    case 'moon':
      return <path d="M20.5 15.5A8.5 8.5 0 0 1 8.5 3.5a8.5 8.5 0 1 0 12 12Z" />;
    case 'paperclip':
      return (
        <path d="m9 12.5 5.7-5.7a3.2 3.2 0 0 1 4.5 4.5l-8 8a5 5 0 0 1-7-7l8.2-8.2" />
      );
    case 'plus':
      return <path d="M12 5v14M5 12h14" />;
    case 'search':
      return (
        <>
          <circle cx="10.5" cy="10.5" r="6.5" />
          <path d="m15.5 15.5 5 5" />
        </>
      );
    case 'sliders':
      return (
        <>
          <path d="M4 6h7M15 6h5M4 12h3M11 12h9M4 18h10M18 18h2" />
          <circle cx="13" cy="6" r="2" />
          <circle cx="9" cy="12" r="2" />
          <circle cx="16" cy="18" r="2" />
        </>
      );
    case 'sun':
      return (
        <>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </>
      );
  }
}

export function Icon({
  name,
  className = '',
  ...props
}: IconProps) {
  return (
    <svg
      className={`ui-icon ${className}`.trim()}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <IconPaths name={name} />
    </svg>
  );
}
