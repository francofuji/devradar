import React from "react";

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: error?.message || "Unexpected render error",
    };
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="app-shell">
          <section className="panel panel--critical">
            <p className="panel__eyebrow">Render guard</p>
            <h1>La UI encontró un error</h1>
            <p>{this.state.message}</p>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
