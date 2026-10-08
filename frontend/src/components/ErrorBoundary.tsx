import { Component, type ErrorInfo, type ReactNode } from 'react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  labels?: {
    title: string;
    unexpected: string;
    returnToChat: string;
  };
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, info);
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="error-boundary">
          <div className="error-boundary__card">
            <span className="error-boundary__icon" aria-hidden="true">
              &#x26A0;
            </span>
            <h2 className="error-boundary__title">
              {this.props.labels?.title ?? 'Something went wrong'}
            </h2>
            <p className="error-boundary__message">
              {this.state.error?.message
                ?? this.props.labels?.unexpected
                ?? 'An unexpected error occurred.'}
            </p>
            <button
              type="button"
              className="error-boundary__button"
              onClick={() => {
                this.setState({ hasError: false, error: null });
                window.location.hash = '';
              }}
            >
              {this.props.labels?.returnToChat ?? 'Return to Chat'}
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
