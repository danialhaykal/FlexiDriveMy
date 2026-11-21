import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "../ui/Button";

// Top-level safety net: a client-side crash anywhere below this (e.g. a
// page dereferencing a pathway that's null because of F005's per-pathway
// "unavailable" degradation - C2/C3a) used to white-screen the whole
// app, since React unmounts the tree on an uncaught render error with no
// boundary in place. One instance wraps the whole app in App.tsx, so any
// page crash is contained to a friendly message instead.

interface ErrorBoundaryProps {
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Unhandled error in a page:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="mx-auto mt-10 flex max-w-xl flex-col items-center gap-4 px-4 text-center">
          <h1 className="text-h2 font-semibold text-ink">Something went wrong on this page</h1>
          <p className="text-small text-ink-muted">
            Please reload the page. If this keeps happening, try again in a few minutes.
          </p>
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
      );
    }

    return this.props.children;
  }
}
