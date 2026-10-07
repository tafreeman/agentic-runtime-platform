import { Component, type ReactNode } from "react";
import ErrorBanner from "./ErrorBanner";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

/**
 * Top-level error boundary.
 * Catches unhandled render errors and shows what failed, that server-side
 * data is unaffected, and how to recover (reload, or go back to the
 * dashboard — which also resets the boundary).
 */
export default class AppErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: unknown): State {
    const message =
      error instanceof Error
        ? error.message
        : "an unexpected error occurred";
    return { hasError: true, message };
  }

  private readonly reset = () => {
    this.setState({ hasError: false, message: "" });
  };

  override render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen items-center justify-center bg-el-canvas">
          <ErrorBanner
            message="This page hit an unexpected error and couldn't be shown."
            dataNote="Your runs, workflows and evaluation results are stored by the API server and are not affected."
            remedy="Reload the page to try again. If it keeps happening, check the browser console for the full error."
            detail={this.state.message}
            onRetry={() => globalThis.location.reload()}
            retryLabel="Reload page"
            onCta={this.reset}
          />
        </div>
      );
    }
    return this.props.children;
  }
}
