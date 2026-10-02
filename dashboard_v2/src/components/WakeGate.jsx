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
// A hung connection never rejects on its own, which would stall the poll loop -- so each
// attempt is capped. After GIVE_UP_MS of failures the card says the API isn't responding
// (a cold start finishes well inside that), but keeps retrying in case it comes back.
const ATTEMPT_TIMEOUT_MS = 10000;
const GIVE_UP_MS = 90000;

export default function WakeGate({ children }) {
  const [awake, setAwake] = useState(false);
  const [unresponsive, setUnresponsive] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer;
    const startedAt = Date.now();

    async function check() {
      try {
        await api.health({ signal: AbortSignal.timeout(ATTEMPT_TIMEOUT_MS) });
        if (!cancelled) setAwake(true);
      } catch {
        if (cancelled) return;
        if (Date.now() - startedAt > GIVE_UP_MS) setUnresponsive(true);
        timer = setTimeout(check, POLL_MS);
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
        {unresponsive ? (
          <>
            <p className="wake-gate-message">The API isn&rsquo;t responding.</p>
            <p className="wake-gate-note">
              It may be down or unreachable. This page keeps retrying, so it will load on its
              own once the API is back &mdash; or try again in a few minutes.
            </p>
          </>
        ) : (
          <>
            <p className="wake-gate-message">Waking up the demo&hellip;</p>
            <p className="wake-gate-note">
              This runs on a free tier that sleeps after a period of inactivity &mdash; the
              first visit after a while can take up to a minute to start. Thanks for your
              patience, it'll only be this slow once.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
