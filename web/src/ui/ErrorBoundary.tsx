import { Component, type ReactNode } from "react";

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };
  static getDerivedStateFromError(error: Error): State {
    return { error };
  }
  componentDidCatch(error: Error, info: unknown) {
    console.error("ErrorBoundary caught", error, info);
  }
  render() {
    if (this.state.error) {
      return (
        <main style={{ padding: 24 }}>
          <h1>Something broke.</h1>
          <pre
            style={{
              background: "var(--color-surface)",
              padding: 12,
              borderRadius: 6,
              overflow: "auto",
            }}
          >
            {String(this.state.error.message ?? this.state.error)}
          </pre>
          <button onClick={() => this.setState({ error: null })}>Dismiss</button>
        </main>
      );
    }
    return this.props.children;
  }
}
