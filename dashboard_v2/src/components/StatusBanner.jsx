import React from "react";

export default function StatusBanner({ loading, loadingText = "Loading...", error }) {
  if (loading) {
    return (
      <p className="status-banner status-loading" role="status">
        {loadingText}
      </p>
    );
  }
  if (error) {
    return (
      <p className="status-banner status-error" role="alert">
        {error.detail || error.message || "Something went wrong."}
      </p>
    );
  }
  return null;
}
