import React, { useEffect, useState } from "react";
import { api } from "../api/client.js";

// The public demo's API runs on a free tier that spins the whole container down after a
// period of inactivity (see deployment/README.md's "Public demo (Render)" section) --
// the first request after a lull can take up to a minute while it wakes back up. Rather
// than let the app render with everything failing, gate it behind a health check so
// visitors see an honest, friendly wait instead of a wall of error banners.
function prefersReducedMotion() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
}

const POLL_MS = 3000;

export default function WakeGate({ children }) {
  const [awake, setAwake] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer;

    async function check() {
      try {
        await api.health();
        if (!cancelled) setAwake(true);
      } catch {
        if (!cancelled) timer = setTimeout(check, POLL_MS);
      }
    }
    check();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  if (awake) return children;

  return (
    <div className="wake-gate">
      <div className="wake-gate-card" role="status">
        <p className="wake-gate-brand">FIN&middot;QA v2</p>
        {!prefersReducedMotion() && <div className="wake-gate-spinner" aria-hidden="true" />}
        <p className="wake-gate-message">Waking up the demo&hellip;</p>
        <p className="wake-gate-note">
          This runs on a free tier that sleeps after a period of inactivity &mdash; the
          first visit after a while can take up to a minute to start. Thanks for your
          patience, it'll only be this slow once.
        </p>
      </div>
    </div>
  );
}
