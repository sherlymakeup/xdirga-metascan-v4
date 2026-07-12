// Phase 5D — scoped panel error boundary. Isolates panel crashes so the
// cockpit shell, safety banners, and command center remain interactive.

import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { reportLovableError } from "@/lib/lovable-error-reporting";

interface Props {
  /** Human-readable scope label ("Orders table", "Equity chart", …). */
  scope: string;
  /** Optional fallback renderer. Receives the error and a retry callback. */
  fallback?: (err: Error, retry: () => void) => ReactNode;
  /** Set to true for chart/table scopes where a retry is safe (idempotent read). */
  canRetry?: boolean;
  children: ReactNode;
}

interface State {
  error: Error | null;
  key: number;
}

export class PanelErrorBoundary extends Component<Props, State> {
  state: State = { error: null, key: 0 };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    reportLovableError(error, {
      scope: this.props.scope,
      componentStack: info.componentStack,
      boundary: "panel",
    });
  }

  retry = () => {
    this.setState((s) => ({ error: null, key: s.key + 1 }));
  };

  render() {
    if (!this.state.error) {
      return <div key={this.state.key}>{this.props.children}</div>;
    }
    if (this.props.fallback) return this.props.fallback(this.state.error, this.retry);
    return (
      <div className="rounded-sm border border-status-crit/40 bg-status-crit/10 p-3 text-[11.5px] text-status-crit">
        <div className="flex items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold uppercase tracking-wider">
              {this.props.scope} failed to render
            </div>
            <div className="mt-0.5 truncate text-status-crit/80" title={this.state.error.message}>
              {this.state.error.message}
            </div>
            {this.props.canRetry && (
              <button
                type="button"
                onClick={this.retry}
                className="mt-2 inline-flex items-center gap-1 rounded-sm border border-status-crit/40 px-2 py-1 text-[10.5px] uppercase tracking-wider hover:bg-status-crit/10"
              >
                <RefreshCw className="h-3 w-3" />
                Retry
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }
}
