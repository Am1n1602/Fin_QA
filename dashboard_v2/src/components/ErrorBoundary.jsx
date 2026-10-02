import React from "react";

// Last-resort net: an uncaught render error would otherwise unmount the whole tree to a
// blank page. Reuses the wake-gate card styling for the fallback.
export default class ErrorBoundary extends React.Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="wake-gate">
        <div className="wake-gate-card" role="alert">
          <p className="wake-gate-brand">FIN&middot;QA v2</p>
          <p className="wake-gate-message">Something went wrong.</p>
          <p className="wake-gate-note">Reload the page to try again.</p>
        </div>
      </div>
    );
  }
}
