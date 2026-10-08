import type { ReactNode } from 'react';
import {
  AppNavigation,
  type NavigationPage,
} from './AppNavigation';

interface AppShellProps {
  currentPage: NavigationPage;
  email: string;
  onNavigate: (page: NavigationPage) => void;
  onNewChat: () => void;
  onLogout: () => void;
  children: ReactNode;
}

export function AppShell({
  currentPage,
  email,
  onNavigate,
  onNewChat,
  onLogout,
  children,
}: AppShellProps) {
  return (
    <div className="app-shell">
      <AppNavigation
        currentPage={currentPage}
        email={email}
        onNavigate={onNavigate}
        onNewChat={onNewChat}
        onLogout={onLogout}
      />
      <div className="app-shell__workspace">{children}</div>
    </div>
  );
}
