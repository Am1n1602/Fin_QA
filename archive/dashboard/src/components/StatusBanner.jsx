import React from "react";

export default function StatusBanner({ loading, error, loadingText = "Loading...", children }) {
  if (loading) {
    return (
      <div className="status-banner status-loading" role="status">
        {loadingText}
      </div>
    );
  }
  if (error) {
    return (
      <div className="status-banner status-error" role="alert">
        <strong>{error.error || "Request failed"}</strong>
        <div>{error.detail || error.message}</div>
      </div>
    );
  }
  return children ?? null;
}