import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  reset = () => this.setState({ error: null });

  render() {
    if (this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset);
      }
      return (
        <div className="p-6 max-w-2xl mx-auto">
          <div className="rounded-md border border-red-300 bg-red-50 p-4">
            <h2 className="text-lg font-semibold text-red-800 mb-1">
              Something went wrong
            </h2>
            <p className="text-sm text-red-700 mb-2">
              {this.state.error.message || "Unknown render error"}
            </p>
            <pre className="text-xs text-red-900 bg-red-100 p-2 rounded overflow-auto max-h-48">
              {this.state.error.stack}
            </pre>
            <div className="mt-3 flex gap-2">
              <button
                onClick={this.reset}
                className="px-3 py-1.5 text-sm rounded-md bg-red-600 text-white hover:bg-red-700"
              >
                Try again
              </button>
              <button
                onClick={() => window.location.reload()}
                className="px-3 py-1.5 text-sm rounded-md bg-gray-200 text-gray-800 hover:bg-gray-300"
              >
                Reload page
              </button>
            </div>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
