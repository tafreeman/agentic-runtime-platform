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
 * Catches unhandled render errors and shows the ASCII [!] error layout.
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

  override render() {
    if (this.state.hasError) {
      return (
        <div className="flex h-screen items-center justify-center bg-b-bg0">
          <ErrorBanner message={this.state.message} />
        </div>
      );
    }
    return this.props.children;
  }
}
